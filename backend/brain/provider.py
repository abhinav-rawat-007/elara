"""LLM provider abstraction.

Elara's brain is swappable: today it's a local Ollama model, but anything that
implements `chat_stream` (Claude, OpenAI, ...) can be dropped in without
touching the agent loop.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

import httpx
import ollama

from .ollama_boot import ensure_ollama


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


def _as_arg_dict(arguments) -> dict:
    """Normalise tool-call arguments to a dict.

    Ollama hands back a ready-made dict, but the OpenAI/Claude-style APIs stream
    `arguments` as a JSON string. Accept either so a new provider can reuse this
    without the agent loop ever seeing a raw string."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class ChatChunk:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False


class LLMProvider(Protocol):
    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[ChatChunk]: ...


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """OpenAI-style registry specs -> Anthropic tool definitions."""
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Map Elara's Ollama-shaped history to Anthropic's format.

    Returns (system_text, messages). The leading system message becomes the
    `system` parameter; mid-history system notes (the nudge) become user turns
    wrapped in <system-note> so the model still sees them. Tool messages become
    tool_result blocks on a user turn, and consecutive same-role messages are
    merged because the API wants alternating turns.
    """
    system = ""
    out: list[dict] = []

    def push(role: str, blocks: list[dict]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if not out and not system:
                system = content
            else:
                push(
                    "user",
                    [{"type": "text", "text": f"<system-note>{content}</system-note>"}],
                )
        elif role == "user":
            if content.strip():
                push("user", [{"type": "text", "text": content}])
        elif role == "assistant":
            blocks: list[dict] = []
            if content.strip():
                blocks.append({"type": "text", "text": content})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id") or uuid.uuid4().hex[:8],
                        "name": fn.get("name", ""),
                        "input": _as_arg_dict(fn.get("arguments")),
                    }
                )
            push("assistant", blocks)
        elif role == "tool":
            push(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id") or uuid.uuid4().hex[:8],
                        "content": content,
                    }
                ],
            )
    # the API requires the conversation to open with a user turn
    if out and out[0]["role"] == "assistant":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continuing our conversation)"}]})
    return system, out


class AnthropicProvider:
    """Cloud brain for complex agentic tasks — same protocol as OllamaProvider."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-5"):
        import anthropic  # imported lazily so the backend boots without a key

        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[ChatChunk]:
        system, mapped = _to_anthropic_messages(messages)
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": mapped,
            "stream": True,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        stream = await self.client.messages.create(**kwargs)
        # tool_use inputs arrive as partial JSON per content block; buffer by
        # block index and emit one ToolCall when the block closes.
        pending: dict[int, dict] = {}
        async for event in stream:
            etype = event.type
            if etype == "content_block_start":
                block = event.content_block
                if block.type == "tool_use":
                    pending[event.index] = {"id": block.id, "name": block.name, "json": ""}
            elif etype == "content_block_delta":
                delta = event.delta
                if delta.type == "text_delta" and delta.text:
                    yield ChatChunk(text=delta.text)
                elif delta.type == "input_json_delta" and event.index in pending:
                    pending[event.index]["json"] += delta.partial_json
            elif etype == "content_block_stop" and event.index in pending:
                tc = pending.pop(event.index)
                yield ChatChunk(
                    tool_calls=[
                        ToolCall(
                            id=tc["id"],
                            name=tc["name"],
                            arguments=_as_arg_dict(tc["json"] or "{}"),
                        )
                    ]
                )
            elif etype == "message_stop":
                yield ChatChunk(done=True)


class OllamaProvider:
    def __init__(self, model: str, host: str = "http://127.0.0.1:11434"):
        self.model = model
        self.host = host
        self.client = ollama.AsyncClient(host=host)

    async def _start_stream(self, kwargs: dict):
        try:
            return await self.client.chat(**kwargs, think=False)
        except TypeError:
            # older ollama client without the `think` kwarg
            return await self.client.chat(**kwargs)

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[ChatChunk]:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": 8192, "temperature": 0.7},
        }
        if tools:
            kwargs["tools"] = tools
        try:
            stream = await self._start_stream(kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # ollama isn't running — boot it and retry once
            if not await asyncio.to_thread(ensure_ollama, self.host):
                raise RuntimeError(
                    "Ollama isn't running and I couldn't start it — is it installed?"
                )
            stream = await self._start_stream(kwargs)

        async for chunk in stream:
            msg = chunk.message
            calls = [
                ToolCall(
                    id=uuid.uuid4().hex[:8],
                    name=tc.function.name,
                    arguments=_as_arg_dict(tc.function.arguments),
                )
                for tc in (msg.tool_calls or [])
            ]
            yield ChatChunk(
                text=msg.content or "",
                tool_calls=calls,
                done=bool(chunk.done),
            )
