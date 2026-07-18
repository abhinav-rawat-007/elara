"""Elara's ears: microphone capture + faster-whisper transcription.

Tries CUDA (RTX 4060) first for speed; falls back to CPU int8 automatically
if the CUDA/cuDNN runtime isn't available — whisper `small` on a 14650HX is
still faster than realtime for short voice commands.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger("elara.stt")

SAMPLE_RATE = 16_000


class Recorder:
    """Push-to-talk microphone capture at 16 kHz mono float32."""

    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self.level: float = 0.0  # rolling RMS for the UI waveform

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        self.level = 0.0

        def callback(indata, _frames, _time, status):
            if status:
                log.debug("mic status: %s", status)
            with self._lock:
                self._chunks.append(indata.copy())
            self.level = float(np.sqrt(np.mean(indata**2)))

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks, axis=0).flatten()
            self._chunks = []
        return audio


class Transcriber:
    """Lazy-loaded faster-whisper model with GPU->CPU fallback."""

    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self._model = None
        self._load_lock = threading.Lock()

    def _load(self):
        from faster_whisper import WhisperModel

        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                model = WhisperModel(
                    self.model_size, device="cuda", compute_type="float16"
                )
                # force weight load / CUDA init with a tiny probe
                list(model.transcribe(np.zeros(1600, dtype=np.float32))[0])
                log.info("whisper '%s' running on CUDA", self.model_size)
            except Exception as exc:
                log.warning("CUDA unavailable for whisper (%s); using CPU int8", exc)
                model = WhisperModel(
                    self.model_size, device="cpu", compute_type="int8"
                )
            self._model = model
            return model

    def warm_up(self) -> None:
        """Call from a background thread at startup so first use is instant."""
        self._load()

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size < SAMPLE_RATE // 4:  # under ~0.25s of audio: ignore
            return ""
        model = self._load()
        segments, _info = model.transcribe(
            audio,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
