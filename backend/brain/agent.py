"""Elara's agent loop: streams model output, executes tool calls, feeds speech.

Protocol events emitted (via the async `emit` callback):
  {type: "assistant_start", id}
  {type: "assistant_delta", id, text}
  {type: "assistant_done", id, text}
  {type: "emotion", name}
  {type: "tool_event", name, status: "start"|"done"|"error", detail}
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Awaitable, Callable

from .personality import emotion_tags, system_prompt
from .provider import LLMProvider
from .streaming import (
    EmotionState,
    EmotionTagFilter,
    SentenceBuffer,
    clean_for_speech,
    ends_with_question,
    looks_like_empty_promise,
)

log = logging.getLogger("elara.agent")

MAX_TOOL_ROUNDS = 6
# The cloud brain gets a much longer leash: multi-step tasks (compare products,
# drive an app step by step) routinely need a dozen-plus tool rounds.
CLOUD_MAX_TOOL_ROUNDS = 24
# A normal chat turn shouldn't sprawl into a monologue. Once she's spoken this
# many sentences in a single turn, stop emitting more — a wall of text is never
# the right answer out loud. Focus mode (multi-step tasks that narrate their
# progress) lifts the cap; see run_turn.
MAX_TURN_SENTENCES = 5
MAX_HISTORY_MESSAGES = 40
# Tool results (page snapshots, window trees) can be huge — cap what enters
# history so one browse doesn't blow the context.
MAX_TOOL_RESULT_CHARS = 8000
# How many stored facts to surface per turn (ranked by relevance) so the
# system prompt stays lean even after she's learned hundreds of them.
MAX_FACTS_IN_PROMPT = 8
# Once the live history passes this many messages, fold the oldest into the
# rolling summary and keep only the most recent COMPACT_KEEP in full.
COMPACT_TRIGGER = 40
COMPACT_KEEP = 20

Emit = Callable[[dict], Awaitable[None]]
OnSentence = Callable[[str, str], Awaitable[None]]  # (sentence, emotion)


class _SpeechBudget:
    """A per-turn cap on how many sentences reach the screen and voice.

    Keeps a runaway reply from becoming a wall of text: once `spoken` hits
    `limit`, `exhausted` goes True and the loop stops emitting. `limit` of None
    means unlimited — used for focus-mode tasks that legitimately narrate many
    steps.
    """

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.spoken = 0

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spoken >= self.limit

PROACTIVE_PROMPT = (
    "{user_name} hasn't said anything for a while. Say ONE short, in-character line "
    "to gently re-open the conversation — a remark that fits the time of day, a "
    "follow-up to something discussed earlier, or something you remember about them. "
    "Never ask if they need help, never apologise for speaking up, and don't be needy. "
    "Two sentences at most. Do not call tools."
)

NUDGE_PROMPT = (
    "You just told {user_name} you would check, but you called no tool — and you "
    "CANNOT follow up later. Call the right tool right now and answer from its "
    "results in this same turn. Do not promise again."
)

# Pseudo-tool offered to the local model when a cloud brain is configured.
# Never executed by the registry — the agent loop intercepts it and switches
# the rest of the turn to the cloud provider with a bigger round budget.
FOCUS_TOOL = {
    "type": "function",
    "function": {
        "name": "enter_focus_mode",
        "description": (
            "Switch into deep-focus mode for any task that needs more than a "
            "couple of tool calls, whatever it involves. Call this FIRST, then "
            "keep working on the task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The full task to accomplish"}
            },
            "required": ["task"],
        },
    },
}

FOCUS_ENGAGED_MSG = (
    "Focus mode engaged — you now have your full toolset and plenty of steps. "
    "Continue the task right now."
)

CLOUD_DOWN_NOTE = (
    "(note: your cloud focus mode is unreachable right now — continue with your "
    "local abilities and tell {user_name} honestly if you can't manage.)"
)

SUMMARY_PROMPT = (
    "Condense the earlier part of this conversation into a compact third-person "
    "summary Elara can use to stay in context. Keep durable facts, decisions, open "
    "threads, and the emotional tone; drop small talk. Write 4-8 terse sentences, "
    "no preamble.\n\n"
    "Existing summary (may be empty):\n{prev}\n\n"
    "New conversation to fold in:\n{transcript}"
)


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        tools,
        user_name: str,
        memory=None,
        cloud_provider: LLMProvider | None = None,
        cloud_mode: str = "auto",
    ):
        self.provider = provider
        self.tools = tools  # tools.Registry
        self.user_name = user_name
        self.memory = memory  # backend.memory.Memory | None
        # hybrid brain: local for chat, cloud for complex agentic turns.
        # cloud_mode: "auto" (local escalates via enter_focus_mode) |
        # "always" (every turn on cloud) | "never". Session updates these live.
        self.cloud_provider = cloud_provider
        self.cloud_mode = cloud_mode
        # continuity across restarts: seed context from stored conversation
        self.history: list[dict] = (
            list(memory.recent_messages(16)) if memory else []
        )
        self._cancel = False  # cooperative stop for the turn in flight

    def reset(self) -> None:
        self.history.clear()
        if self.memory:
            self.memory.clear_messages()
            self.memory.set_summary("")

    def cancel(self) -> None:
        """Ask the in-flight turn to stop after the current chunk. Lets a fresh
        message actually cut the previous one off, not just its speech."""
        self._cancel = True

    def _cloud_available(self) -> bool:
        return self.cloud_provider is not None and self.cloud_mode != "never"

    def _messages(self, query: str = "") -> list[dict]:
        facts = summary = None
        if self.memory:
            facts = self.memory.relevant_facts(query, MAX_FACTS_IN_PROMPT)
            summary = self.memory.get_summary()
        return [
            {
                "role": "system",
                "content": system_prompt(
                    self.user_name, facts, summary,
                    focus_mode=self._cloud_available() and self.cloud_mode == "auto",
                ),
            },
            *self.history[-MAX_HISTORY_MESSAGES:],
        ]

    @staticmethod
    async def _speak(
        sents: list[str],
        on_sentence: OnSentence,
        emotion: EmotionState,
        budget: _SpeechBudget | None = None,
    ) -> None:
        for sent in sents:
            if budget is not None and budget.exhausted:
                return
            spoken = clean_for_speech(sent)
            if spoken:
                if budget is not None:
                    budget.spoken += 1
                await on_sentence(spoken, emotion.current)

    async def _stream_once(
        self,
        messages: list[dict],
        tool_specs,
        reply_id: str,
        sentences: SentenceBuffer,
        tags: EmotionTagFilter,
        emotion: EmotionState,
        emit: Emit,
        on_sentence: OnSentence,
        provider: LLMProvider | None = None,
        budget: _SpeechBudget | None = None,
    ) -> tuple[str, list]:
        """One model stream: filters emotion tags, emits deltas, feeds TTS.

        Returns (visible_text, tool_calls) for the round. Stops early if the
        turn has been cancelled. Once `budget` is exhausted, text is dropped
        rather than emitted — screen, voice, and the returned text stay in
        lockstep so the transcript never shows what the voice never said.
        """
        round_text = ""
        tool_calls = []
        async for chunk in (provider or self.provider).chat_stream(messages, tool_specs):
            if self._cancel:
                break
            if chunk.text:
                text, felt = tags.feed(chunk.text)
                emotion.update(felt)
                for name in felt:
                    await emit({"type": "emotion", "name": name})
                if text and not (budget is not None and budget.exhausted):
                    round_text += text
                    await emit(
                        {"type": "assistant_delta", "id": reply_id, "text": text}
                    )
                    await self._speak(sentences.feed(text), on_sentence, emotion, budget)
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
        tail = tags.flush()
        if tail and not (budget is not None and budget.exhausted):
            round_text += tail
            await emit({"type": "assistant_delta", "id": reply_id, "text": tail})
            await self._speak(sentences.feed(tail), on_sentence, emotion, budget)
        return round_text, tool_calls

    async def run_turn(self, user_text: str, emit: Emit, on_sentence: OnSentence) -> str:
        """One full user turn, including any tool-call rounds. Returns her final reply."""
        self._cancel = False
        self.history.append({"role": "user", "content": user_text})
        if self.memory:
            self.memory.add_message("user", user_text)
        reply_id = uuid.uuid4().hex[:8]
        await emit({"type": "assistant_start", "id": reply_id})

        sentences = SentenceBuffer()
        tags = EmotionTagFilter(emotion_tags())
        emotion = EmotionState()
        parts: list[str] = []  # visible text per round, joined for the final reply
        round_text = ""
        # turn-only system notes (the nudge, a cloud-down apology) — injected to
        # steer this turn, then removed so they never pollute her memory
        transient: list[dict] = []
        nudged = False

        # pick the brain for this turn; "auto" starts local and may escalate
        # mid-turn when she calls enter_focus_mode
        provider: LLMProvider = self.provider
        rounds_budget = MAX_TOOL_ROUNDS
        # a chat turn is capped to a few sentences; focus-mode tasks narrate
        # progress across many steps, so they run uncapped (limit=None)
        speech = _SpeechBudget(MAX_TURN_SENTENCES)
        if self._cloud_available() and self.cloud_mode == "always":
            provider, rounds_budget = self.cloud_provider, CLOUD_MAX_TOOL_ROUNDS
            speech.limit = None

        rounds = 0
        finished = False  # False after the loop means the round budget ran out
        while rounds < rounds_budget:
            rounds += 1
            specs = self.tools.specs()
            if self._cloud_available() and provider is self.provider:
                specs = specs + [FOCUS_TOOL]
            try:
                round_text, tool_calls = await self._stream_once(
                    self._messages(user_text),
                    specs,
                    reply_id,
                    sentences,
                    tags,
                    emotion,
                    emit,
                    on_sentence,
                    provider=provider,
                    budget=speech,
                )
            except Exception:
                if provider is not self.provider:
                    # cloud brain unreachable — drop back to local and keep going
                    log.warning(
                        "cloud provider failed; falling back to local", exc_info=True
                    )
                    provider = self.provider
                    rounds_budget = max(rounds + 2, MAX_TOOL_ROUNDS)
                    note = {
                        "role": "system",
                        "content": CLOUD_DOWN_NOTE.format(user_name=self.user_name),
                    }
                    self.history.append(note)
                    transient.append(note)
                    continue
                raise
            # A "let me check…" preamble that precedes a tool call is spoken once,
            # live, and then kept out of the transcript — the answer round stands
            # on its own. Real content and progress lines are never filler.
            is_filler_round = bool(tool_calls) and looks_like_empty_promise(round_text)
            if round_text and not is_filler_round:
                parts.append(round_text)

            if self._cancel:
                self.history.append({"role": "assistant", "content": round_text})
                finished = True
                break

            # She asked {user_name} something — yield the turn and wait for the
            # answer, even if the model queued more tool calls in the same breath.
            # Running them now is the "asked, then kept working without waiting"
            # bug. Drop the queued calls; store her words as a plain turn so no
            # dangling tool_calls linger in history. (A tool-less round already
            # ends the turn below.)
            if tool_calls and ends_with_question(round_text):
                self.history.append({"role": "assistant", "content": round_text})
                finished = True
                break

            if not tool_calls:
                self.history.append({"role": "assistant", "content": round_text})
                if not nudged and looks_like_empty_promise(round_text):
                    # she promised to check but called nothing — make her do it
                    nudged = True
                    note = {
                        "role": "system",
                        "content": NUDGE_PROMPT.format(user_name=self.user_name),
                    }
                    self.history.append(note)
                    transient.append(note)
                    continue
                finished = True
                break

            self.history.append(
                {
                    "role": "assistant",
                    "content": round_text,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                await emit(
                    {
                        "type": "tool_event",
                        "name": tc.name,
                        "status": "start",
                        "detail": tc.arguments,
                    }
                )
                if tc.name == "enter_focus_mode":
                    # intercepted, never executed: swap in the cloud brain for
                    # the rest of this turn and extend the round budget
                    if self._cloud_available() and provider is self.provider:
                        provider, rounds_budget = self.cloud_provider, CLOUD_MAX_TOOL_ROUNDS
                        speech.limit = None  # a focus task may narrate many steps
                        result = {"ok": True, "message": FOCUS_ENGAGED_MSG}
                    else:
                        result = {
                            "ok": False,
                            "error": "focus mode isn't available right now — "
                            "continue with your usual tools",
                        }
                    await emit(
                        {
                            "type": "tool_event",
                            "name": tc.name,
                            "status": "done" if result["ok"] else "error",
                            "detail": result.get("message", result.get("error", "")),
                        }
                    )
                else:
                    try:
                        result = await self.tools.execute(tc.name, tc.arguments)
                        await emit(
                            {
                                "type": "tool_event",
                                "name": tc.name,
                                "status": "done",
                                "detail": result.get("message", ""),
                            }
                        )
                    except Exception as exc:  # tool crashed — tell the model, not the user
                        result = {"ok": False, "error": str(exc)}
                        await emit(
                            {
                                "type": "tool_event",
                                "name": tc.name,
                                "status": "error",
                                "detail": str(exc),
                            }
                        )
                content = json.dumps(result, ensure_ascii=False, default=str)
                if len(content) > MAX_TOOL_RESULT_CHARS:
                    content = content[:MAX_TOOL_RESULT_CHARS] + "…[truncated]"
                self.history.append(
                    {
                        "role": "tool",
                        "tool_name": tc.name,
                        "tool_call_id": tc.id,
                        "content": content,
                    }
                )

        if not finished:
            # ran out of tool rounds without a final answer
            self.history.append({"role": "assistant", "content": round_text})

        for note in transient:
            # the steering was for this turn only — keep it out of her memory
            try:
                self.history.remove(note)
            except ValueError:
                pass

        await self._speak(sentences.flush(), on_sentence, emotion, speech)

        # join rounds with a space so "Let me check" + "It's sunny" doesn't
        # render as "Let me checkIt's sunny"
        full_reply = " ".join(p.strip() for p in parts if p.strip())

        if not full_reply.strip() and not self._cancel:
            # model went silent (e.g. only tool calls) — never leave the user hanging
            fallback = "Done."
            full_reply = fallback
            await emit({"type": "assistant_delta", "id": reply_id, "text": fallback})
            await on_sentence(fallback, emotion.current)
            self.history.append({"role": "assistant", "content": fallback})

        if self.memory and full_reply.strip():
            self.memory.add_message("assistant", full_reply)
        await emit({"type": "assistant_done", "id": reply_id, "text": full_reply})
        await self._maybe_compact()
        return full_reply

    async def run_proactive(self, emit: Emit, on_sentence: OnSentence) -> str:
        """An unprompted line from Elara after a quiet stretch. No tools.

        The nudge is a transient system instruction — only her reply enters
        history/memory, so the context never accumulates fake user turns.
        """
        self._cancel = False
        messages = self._messages() + [
            {
                "role": "system",
                "content": PROACTIVE_PROMPT.format(user_name=self.user_name),
            }
        ]
        reply_id = uuid.uuid4().hex[:8]
        await emit({"type": "assistant_start", "id": reply_id})

        sentences = SentenceBuffer()
        tags = EmotionTagFilter(emotion_tags())
        emotion = EmotionState()
        # an unprompted nudge should be a line or two, never a monologue
        speech = _SpeechBudget(3)
        reply, _ = await self._stream_once(
            messages, None, reply_id, sentences, tags, emotion, emit, on_sentence,
            budget=speech,
        )
        await self._speak(sentences.flush(), on_sentence, emotion, speech)

        reply = reply.strip()
        if reply:
            self.history.append({"role": "assistant", "content": reply})
            if self.memory:
                self.memory.add_message("assistant", reply)
        await emit({"type": "assistant_done", "id": reply_id, "text": reply})
        return reply

    async def _maybe_compact(self) -> None:
        """Fold the oldest history into a rolling summary once it grows long,
        so a marathon conversation stays in context without ballooning the
        prompt. Best-effort: a summarization failure just leaves history as-is."""
        if not self.memory or len(self.history) <= COMPACT_TRIGGER:
            return
        overflow = self.history[:-COMPACT_KEEP]
        transcript = "\n".join(
            f"{m['role']}: {m['content']}"
            for m in overflow
            if m.get("role") in ("user", "assistant") and m.get("content", "").strip()
        )
        if not transcript.strip():
            self.history = self.history[-COMPACT_KEEP:]
            return
        try:
            summary = await self._summarize(self.memory.get_summary(), transcript)
        except Exception:
            log.warning("history compaction failed; leaving history intact", exc_info=True)
            return
        if summary.strip():
            self.memory.set_summary(summary.strip())
            self.history = self.history[-COMPACT_KEEP:]

    async def _summarize(self, prev: str, transcript: str) -> str:
        prompt = SUMMARY_PROMPT.format(prev=prev or "(none)", transcript=transcript)
        messages = [{"role": "user", "content": prompt}]
        out = ""
        async for chunk in self.provider.chat_stream(messages, None):
            if chunk.text:
                out += chunk.text
        return out
