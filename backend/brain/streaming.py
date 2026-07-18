"""Pure text-stream helpers for the agent loop.

These have no LLM/network dependencies so they can be unit-tested in isolation:
splitting a token stream into speakable sentences, stripping [emotion] tags
that arrive split across chunk boundaries, cleaning stage directions out of
text before it reaches the voice, and spotting the empty "let me check…"
promise a small model makes when it forgets to actually call a tool.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?])$|\n+")
# asterisk spans are always a stage direction ("*laughs*", "*sighs*"), never
# spoken content — drop the whole span, not just the asterisks, or the voice
# reads the action out loud as flat, robotic-sounding text.
_STAGE_DIRECTION = re.compile(r"\*[^*\n]{1,40}\*")
# strip anything a voice shouldn't read out loud
_SPEECH_JUNK = re.compile(r"[*_#`>|~\[\]]|:\w+:|[\U0001F000-\U0001FAFF☀-➿]")

# Small local models love saying "let me check and I'll let you know" and then
# stopping without calling any tool — a dead-end, since she can't follow up on
# her own. When a round ends tool-less on such a promise, we call her on it.
_PROMISE_RE = re.compile(
    r"\b(let me (check|look|search|see|find|dig)|"
    r"i[’']?ll (check|look|search|find|dig|get back|let you know)|"
    r"let you know|get back to you|"
    r"(one|a|give me a) (moment|sec|second|minute)|"
    r"hold on|hang on)\b",
    re.IGNORECASE,
)


def clean_for_speech(text: str) -> str:
    text = _STAGE_DIRECTION.sub("", text)
    return _SPEECH_JUNK.sub("", text).strip()


def looks_like_empty_promise(text: str) -> bool:
    """True if the text promises to go check on something (and, tool-less, lied)."""
    return bool(_PROMISE_RE.search(text))


# trailing quotes/brackets a question mark can hide behind, e.g. '... dive in?"'
_Q_TRAILING = " \t\r\n\"'“”‘’)]}»"


def ends_with_question(text: str) -> bool:
    """True if the visible text ends by asking the user something.

    The cue to yield the turn and wait for their answer, rather than barrel on
    with more tool calls in the same breath (the "asked, then kept working"
    bug). Trailing quotes and brackets are ignored so '... dive in?"' still
    counts.
    """
    return clean_for_speech(text).rstrip(_Q_TRAILING).endswith("?")


class SentenceBuffer:
    """Accumulates streamed deltas and yields complete sentences for TTS."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        parts = _SENTENCE_END.split(self._buf)
        if len(parts) <= 1:
            return []
        *complete, self._buf = parts
        return [s.strip() for s in complete if s.strip()]

    def flush(self) -> list[str]:
        rest = self._buf.strip()
        self._buf = ""
        return [rest] if rest else []


# what a tag may look like between brackets, once lowercased
_TAG_WORD = re.compile(r"[a-z][a-z_-]{0,18}")
# longest trailing text worth holding back as a possibly-unfinished tag
_TAG_HOLD_MAX = 22


class EmotionTagFilter:
    """Strips [emotion] tags from streamed text, reporting recognised ones.

    Tags arrive split across arbitrary chunk boundaries, so a trailing
    unclosed '[' is held back until it closes or grows too long to be a tag.
    Unrecognised single-word tags are dropped silently — better a lost word
    than the voice reading a hallucinated stage direction aloud.
    """

    def __init__(self, known: set[str]):
        self._known = known
        self._held = ""
        self._last_out = ""  # last char emitted, for collapsing doubled spaces
        self._swallow_space = False  # tag ended a chunk; eat the next chunk's lead space

    def feed(self, delta: str) -> tuple[str, list[str]]:
        buf = self._held + delta
        self._held = ""
        if self._swallow_space:
            self._swallow_space = False
            if buf.startswith(" ") and self._last_out in ("", " ", "\n"):
                buf = buf[1:]
        out: list[str] = []
        felt: list[str] = []
        i = 0
        while i < len(buf):
            ch = buf[i]
            if ch != "[":
                out.append(ch)
                i += 1
                continue
            close = buf.find("]", i + 1)
            if close == -1:
                tail = buf[i:]
                if len(tail) <= _TAG_HOLD_MAX:
                    self._held = tail  # tag may still be streaming in
                else:
                    out.append(tail)  # too long to be a tag — let it through
                break
            word = buf[i + 1 : close].strip().lower()
            if _TAG_WORD.fullmatch(word):
                if word in self._known:
                    felt.append(word)
                i = close + 1
                # swallow one space after the tag unless that would glue words
                prev = out[-1] if out else self._last_out
                if prev in ("", " ", "\n"):
                    if i < len(buf) and buf[i] == " ":
                        i += 1
                    elif i == len(buf):
                        self._swallow_space = True  # space may lead the next chunk
            else:
                out.append(ch)  # not a tag — keep the bracket literally
                i += 1
        if out:
            self._last_out = out[-1]
        return "".join(out), felt

    def flush(self) -> str:
        """Whatever is still held at stream end wasn't a tag — release it."""
        held, self._held = self._held, ""
        return held


class EmotionState:
    """Her current feeling, as last signalled by an [emotion] tag this turn.

    Tags arrive right before the words they colour (see personality.py's
    feeling rules), so the sentence(s) that follow a tag inherit it until
    the next one — this just tracks that "last felt" value across a turn.
    """

    def __init__(self) -> None:
        self.current = "neutral"

    def update(self, felt: list[str]) -> None:
        if felt:
            self.current = felt[-1]
