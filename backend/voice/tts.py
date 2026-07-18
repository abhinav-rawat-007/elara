"""Elara's voice: Kokoro-82M local neural TTS with sentence-level streaming playback.

Sentences are queued as the LLM streams them and flow through a two-stage
pipeline: a synthesis worker turns text into PCM ahead of time while a
playback worker plays finished audio back-to-back — so she starts talking
before her full reply is generated and there is no synthesis gap between
sentences.

The first queued sentence is synthesized alone (fast time-to-first-audio);
after that the synthesis worker batches whatever sentences have piled up
while she was talking into one chunk, so intonation and pacing flow across
sentence boundaries instead of resetting at every full stop.

Synthesis runs fully offline via kokoro-onnx. Model files live in
backend/models/kokoro/ (see MODEL_URL below, ~340 MB one-time download).
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro

from backend.paths import models_dir

log = logging.getLogger("elara.tts")

# Per-emotion prosody: (speed multiplier, gain multiplier, trailing pause s).
# Kokoro only exposes a speed knob, so pace + loudness + a beat of silence do
# the work real vocal cords would — a flat "1.0 always" read is what makes
# TTS sound like TTS. A small random jitter is layered on top of speed per
# chunk so even same-emotion lines don't land at an identical, metronomic pace.
EMOTION_PROSODY: dict[str, tuple[float, float, float]] = {
    "neutral": (1.00, 1.00, 0.00),
    "joy": (1.07, 1.08, 0.00),
    "tease": (1.04, 1.03, 0.05),
    "curious": (1.02, 1.00, 0.05),
    "soft": (0.92, 0.85, 0.15),
    "alert": (1.10, 1.08, 0.00),
    "sigh": (0.90, 0.88, 0.35),
}
_SPEED_JITTER = 0.03  # +/- fraction of speed, so pacing isn't perfectly identical

MODELS_DIR = models_dir()
MODEL_PATH = MODELS_DIR / "kokoro-v1.0.onnx"
VOICES_PATH = MODELS_DIR / "voices-v1.0.bin"
MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"
)

_kokoro: Kokoro | None = None
_load_lock = threading.Lock()
# espeak-ng phonemization inside Kokoro.create is not thread-safe
_synth_lock = threading.Lock()

# Caps for batching queued sentences into one synthesis chunk. Bigger chunks
# mean better cross-sentence prosody but a longer wait for that chunk's audio.
MAX_CHUNK_SENTENCES = 3
MAX_CHUNK_CHARS = 350


def _get_kokoro() -> Kokoro:
    global _kokoro
    with _load_lock:
        if _kokoro is None:
            if not (MODEL_PATH.exists() and VOICES_PATH.exists()):
                raise RuntimeError(
                    f"Kokoro model files missing in {MODELS_DIR} — download "
                    f"kokoro-v1.0.onnx and voices-v1.0.bin from {MODEL_URL}"
                )
            log.info("loading Kokoro TTS model")
            _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        return _kokoro


_blend_cache: dict[str, np.ndarray] = {}


def _resolve_voice(voice: str) -> str | np.ndarray:
    """A plain Kokoro voice id, or a "+"-joined blend averaged into one style
    vector — e.g. "af_bella+af_nicole" mixes bella's brightness with
    nicole's breathiness into a tone unique to Elara, not a stock preset."""
    if "+" not in voice:
        return voice
    if voice not in _blend_cache:
        kokoro = _get_kokoro()
        styles = [kokoro.get_voice_style(name) for name in voice.split("+")]
        _blend_cache[voice] = np.mean(styles, axis=0).astype(np.float32)
    return _blend_cache[voice]


def warm_up(voice: str = "af_bella+af_nicole") -> None:
    """Load the model and run one tiny synthesis so her first reply isn't slow."""
    synthesize("Ready.", voice)
    log.info("Kokoro TTS warmed up")


def synthesize(text: str, voice: str, speed: float = 1.0) -> tuple[np.ndarray, int]:
    """Text -> (float32 samples, sample_rate). Blocking; run off the event loop."""
    # Kokoro voice ids encode the accent in their first letter (a=US, b=British)
    lang = "en-gb" if voice.startswith("b") else "en-us"
    with _synth_lock:
        return _get_kokoro().create(
            text, voice=_resolve_voice(voice), speed=speed, lang=lang
        )


class Speaker:
    """Pipelined queue of sentences -> synthesis + playback, interruptible.

    Synthesis runs ahead of playback (bounded prefetch) so the next sentence's
    audio is ready the moment the current one ends.
    """

    def __init__(self, emit, get_voice, is_enabled):
        self._emit = emit  # async fn(dict)
        self._get_voice = get_voice  # () -> str
        self._is_enabled = is_enabled  # () -> bool
        self._text_q: asyncio.Queue[tuple[int, str, str]] = asyncio.Queue()
        self._audio_q: asyncio.Queue[tuple[int, np.ndarray, int]] = asyncio.Queue(
            maxsize=4
        )
        self._stop_flag = threading.Event()
        self._generation = 0  # bumped on interrupt; stale pipeline items are dropped
        self._synthesizing = False
        self._speaking = False
        self._synth_task: asyncio.Task | None = None
        self._play_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._synth_task is None:
            self._synth_task = asyncio.create_task(self._synth_loop())
            self._play_task = asyncio.create_task(self._play_loop())

    @property
    def speaking(self) -> bool:
        return (
            self._speaking
            or self._synthesizing
            or not self._text_q.empty()
            or not self._audio_q.empty()
        )

    async def say(self, sentence: str, emotion: str = "neutral") -> None:
        if self._is_enabled():
            await self._text_q.put((self._generation, sentence, emotion))

    def interrupt(self) -> None:
        """Stop current playback and drop everything queued or in flight."""
        self._generation += 1
        for q in (self._text_q, self._audio_q):
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self._stop_flag.set()
        sd.stop()

    def _pipeline_empty(self) -> bool:
        return (
            self._text_q.empty() and self._audio_q.empty() and not self._synthesizing
        )

    def _next_chunk(self, first: str) -> str:
        """Batch already-queued sentences onto `first`, within the chunk caps."""
        parts = [first]
        while (
            len(parts) < MAX_CHUNK_SENTENCES
            and sum(len(p) for p in parts) < MAX_CHUNK_CHARS
            and not self._text_q.empty()
        ):
            gen, sentence, _emotion = self._text_q.get_nowait()
            if gen == self._generation:
                parts.append(sentence)
        if len(parts) == 1:
            return first
        # joined mid-thought lines need terminal punctuation to read right
        return " ".join(p if not p[-1].isalnum() else p + "." for p in parts)

    @staticmethod
    def _prosody(emotion: str) -> tuple[float, float, float]:
        return EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])

    async def _synth_loop(self) -> None:
        while True:
            gen, sentence, emotion = await self._text_q.get()
            if gen != self._generation:
                continue
            self._synthesizing = True
            try:
                chunk = self._next_chunk(sentence)
                base_speed, gain, pause_s = self._prosody(emotion)
                speed = max(0.5, min(2.0, base_speed + random.uniform(
                    -_SPEED_JITTER, _SPEED_JITTER
                )))
                samples, rate = await asyncio.to_thread(
                    synthesize, chunk, self._get_voice(), speed
                )
                if gain != 1.0:
                    samples = np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
                if pause_s > 0 and len(samples):
                    silence = np.zeros(int(rate * pause_s), dtype=np.float32)
                    samples = np.concatenate([samples, silence])
                if len(samples) and gen == self._generation:
                    await self._audio_q.put((gen, samples, rate))
            except Exception as exc:
                log.warning("TTS failed for %r: %s", sentence[:40], exc)
            finally:
                self._synthesizing = False

    async def _play_loop(self) -> None:
        while True:
            gen, samples, rate = await self._audio_q.get()
            if gen != self._generation:
                continue
            self._stop_flag.clear()
            if not self._speaking:
                self._speaking = True
                await self._emit({"type": "status", "state": "speaking"})
            await asyncio.to_thread(self._play, samples, rate)
            if self._pipeline_empty():
                self._speaking = False
                await self._emit({"type": "status", "state": "idle"})

    def _play(self, samples: np.ndarray, rate: int) -> None:
        sd.play(samples, rate)
        while True:
            stream = sd.get_stream()
            if stream is None or not stream.active or self._stop_flag.is_set():
                break
            sd.sleep(50)
        if self._stop_flag.is_set():
            sd.stop()
