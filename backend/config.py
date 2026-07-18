"""Elara backend configuration — persisted to config.json next to this file."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields

from backend.paths import data_dir

log = logging.getLogger("elara.config")

CONFIG_PATH = data_dir() / "config.json"

# Elara speaks with exactly one voice — not user-configurable. A custom
# blend of two Kokoro presets (see backend/voice/tts.py's blending support):
# af_bella (bright, confident) + af_nicole (breathy, husky) for a strong,
# sultry tone unique to her rather than an off-the-shelf preset.
VOICE = "af_bella+af_nicole"


@dataclass
class Config:
    model: str = "qwen3:8b"
    speak_replies: bool = True
    stt_model: str = "small"
    user_name: str = "friend"
    ollama_host: str = "http://127.0.0.1:11434"
    # she may speak up unprompted after this long a lull (0 disables via toggle)
    proactive: bool = True
    proactive_minutes: int = 12
    # hybrid brain: local Ollama for chat, Claude for complex agentic tasks.
    # cloud_mode: "auto" (she escalates herself) | "always" | "never"
    # cloud_backend: "auto" (prefer the Claude subscription via Claude Code,
    # else API key) | "subscription" | "api"
    anthropic_api_key: str = ""
    cloud_model: str = "claude-sonnet-5"
    cloud_mode: str = "auto"
    cloud_backend: str = "auto"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.apply_patch(data)
            except json.JSONDecodeError:
                log.warning("config.json is not valid JSON — using defaults")
        return cfg

    def apply_patch(self, patch: dict) -> None:
        """Update fields from an (untrusted) dict, coercing each to its declared
        type and dropping anything unknown or uncoercible. This is the only path
        by which the UI (or a dev-mode client) mutates config, so it must never
        leave a field holding a value of the wrong type."""
        if not isinstance(patch, dict):
            return
        types = {f.name: f.type for f in fields(self)}
        for key, value in patch.items():
            if key not in types:
                continue  # ignore unknown keys
            coerced = _coerce(types[key], value)
            if coerced is None:
                log.warning("ignoring config %s=%r (wrong type)", key, value)
                continue
            setattr(self, key, coerced)
        # keep the proactive countdown in a sane range
        self.proactive_minutes = max(1, min(240, int(self.proactive_minutes)))
        if self.cloud_mode not in ("auto", "always", "never"):
            self.cloud_mode = "auto"
        if self.cloud_backend not in ("auto", "subscription", "api"):
            self.cloud_backend = "auto"

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def as_dict(self) -> dict:
        return asdict(self)


def _coerce(field_type, value):
    """Best-effort coerce `value` to a dataclass field's type. Returns the
    coerced value, or None if it can't be represented as that type."""
    # dataclass field types come through as strings under `from __future__
    # import annotations`, so match on the name.
    name = getattr(field_type, "__name__", str(field_type))
    try:
        if name == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes", "on")
            if isinstance(value, (int, float)):
                return bool(value)
            return None
        if name == "int":
            if isinstance(value, bool):  # bool is an int subclass — reject
                return None
            return int(value)
        if name == "float":
            return float(value)
        if name == "str":
            return value if isinstance(value, str) else None
    except (ValueError, TypeError):
        return None
    return None
