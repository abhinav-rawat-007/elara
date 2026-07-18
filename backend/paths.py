"""Where Elara's files live — in dev and when frozen into a sidecar exe.

Running from source, everything sits under backend/. But once PyInstaller
bundles the backend into a single elara-backend.exe, `__file__` points inside a
temporary extraction directory that is wiped on exit — so config.json and the
SQLite DB must NOT be written relative to the code, or they vanish every run.

Three roots keep that straight:
  - resource_dir(): read-only files that ship inside the bundle (character card).
  - data_dir():     user data we read AND write (config, elara.db) — stable and
                    writable across runs.
  - models_dir():   the big Kokoro model download, kept out of the bundle and
                    fetched once into a stable spot.

In dev all three resolve back to backend/, so behaviour is unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Read-only resources bundled with the code."""
    if is_frozen():
        # PyInstaller unpacks data files under _MEIPASS.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _BACKEND_DIR


def data_dir() -> Path:
    """A stable, writable directory for config + database."""
    if is_frozen():
        base = Path(os.environ.get("APPDATA") or Path.home()) / "Elara"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return _BACKEND_DIR


def models_dir() -> Path:
    """Where the ~340 MB Kokoro model files live (downloaded separately)."""
    if is_frozen():
        base = data_dir() / "models" / "kokoro"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return _BACKEND_DIR / "models" / "kokoro"
