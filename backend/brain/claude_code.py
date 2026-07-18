"""Cloud brain on the user's Claude subscription, via the Claude Agent SDK.

The Anthropic API bills per token; a Claude Pro/Max subscription doesn't cover
it. What the subscription DOES cover is Claude Code — and the Claude Agent SDK
is Claude Code as a library, authenticating through the user's existing
`claude` login. This provider routes focus-mode turns through it, so complex
tasks cost subscription usage instead of API credits.

Shape: same LLMProvider protocol as OllamaProvider/AnthropicProvider, but the
SDK runs its own internal tool loop — one chat_stream call performs the whole
task and yields only text, so Elara's outer loop sees a plain final answer.
Her tools are mounted into the SDK session as an in-process MCP server, which
means guarded tools (confirm=true, browser_guard, shell_guard) keep their
guards, and tool events still reach the UI via the session ToolContext.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import AsyncIterator

from backend.tools.registry import registry

from .provider import ChatChunk

log = logging.getLogger("elara.claude_code")

# Claude Code's built-in tools that act on the PC outside Elara's guarded
# toolset. Blocked — she acts through her own tools, which carry the
# confirmation gates. Read-only built-ins (Read, Grep, Glob, WebSearch,
# WebFetch) stay available as a bonus.
_DISALLOWED_BUILTINS = ["Bash", "Write", "Edit", "NotebookEdit"]

MAX_SDK_TURNS = 40
_MCP_PREFIX = "mcp__elara__"


def available() -> bool:
    """True if the Agent SDK is importable and a claude login can exist."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    # the wheel bundles its own CLI, so a PATH claude is optional — but its
    # presence is the best cheap signal that the user actually uses Claude Code
    return True


def _short(tool_name: str) -> str:
    return tool_name.removeprefix(_MCP_PREFIX)


def _make_handler(t):
    async def handler(args: dict) -> dict:
        result = await registry.execute(t.name, args or {})
        ctx = registry.context()
        if ctx.emit:
            await ctx.emit(
                {
                    "type": "tool_event",
                    "name": t.name,
                    "status": "done" if result.get("ok") else "error",
                    "detail": result.get("message", result.get("error", "")),
                }
            )
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }
            ]
        }

    return handler


def _build_server():
    """Elara's whole tool registry as an in-process MCP server."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    sdk_tools = [
        tool(t.name, t.description, t.parameters)(_make_handler(t))
        for t in registry.all()
    ]
    return create_sdk_mcp_server(name="elara", version="1.0.0", tools=sdk_tools)


def to_prompt(messages: list[dict]) -> tuple[str, str]:
    """Split Elara's message history into (system_prompt, task_prompt).

    Each focus task is a fresh SDK session, so recent conversation is folded
    into the prompt as a transcript for context.
    """
    system = ""
    lines: list[str] = []
    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "system":
            if not system and not lines:
                system = content
            # mid-history system notes (nudge etc.) don't matter to a fresh session
        elif role == "user" and content:
            lines.append(f"User: {content}")
        elif role == "assistant" and content:
            lines.append(f"You (earlier): {content}")
        # tool messages are stale context for a fresh session — skip
    transcript = "\n".join(lines[-24:])
    if not transcript:
        return system, "Continue helping the user."
    task = (
        "Here is the recent conversation. Continue it by DOING the user's "
        "latest request now, using your tools, then answer in character.\n\n"
        f"{transcript}"
    )
    return system, task


class ClaudeCodeProvider:
    """LLMProvider backed by the local Claude Code install (subscription-billed)."""

    def __init__(self, model: str | None = None):
        # None -> whatever the user's subscription/plan defaults to
        self.model = model

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[ChatChunk]:
        # `tools` (Elara's specs) is ignored on purpose: the same tools are
        # mounted via MCP and the SDK loops over them internally.
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        system, task = to_prompt(messages)
        options = ClaudeAgentOptions(
            system_prompt=system or None,
            model=self.model,
            mcp_servers={"elara": _build_server()},
            disallowed_tools=_DISALLOWED_BUILTINS,
            permission_mode="bypassPermissions",
            max_turns=MAX_SDK_TURNS,
        )
        ctx = registry.context()
        async with ClaudeSDKClient(options=options) as client:
            await client.query(task)
            async for msg in client.receive_response():
                kind = type(msg).__name__
                if kind == "AssistantMessage":
                    for block in msg.content:
                        btype = type(block).__name__
                        if btype == "TextBlock" and block.text:
                            yield ChatChunk(text=block.text)
                        elif btype == "ToolUseBlock" and ctx.emit:
                            await ctx.emit(
                                {
                                    "type": "tool_event",
                                    "name": _short(block.name),
                                    "status": "start",
                                    "detail": block.input,
                                }
                            )
                elif kind == "ResultMessage":
                    if getattr(msg, "is_error", False):
                        raise RuntimeError(
                            f"claude code session failed: {getattr(msg, 'result', '')}"
                        )
                    yield ChatChunk(done=True)


def cli_on_path() -> bool:
    return shutil.which("claude") is not None
