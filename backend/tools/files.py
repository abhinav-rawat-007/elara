"""Finding and opening files on the PC."""

from __future__ import annotations

import os
from pathlib import Path

from .registry import registry

_SEARCH_ROOTS = [
    Path.home() / d
    for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")
]
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "AppData"}
_MAX_RESULTS = 20
_MAX_DEPTH = 6


@registry.tool(
    "Search the user's personal folders (Desktop, Documents, Downloads, Pictures, "
    "Videos, Music) for files or folders by name.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Part of the file/folder name"}
        },
        "required": ["name"],
    },
)
def find_files(name: str) -> dict:
    query = name.strip().lower()
    hits: list[str] = []
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= _MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            for entry in dirnames + filenames:
                if query in entry.lower():
                    hits.append(str(Path(dirpath) / entry))
                    if len(hits) >= _MAX_RESULTS:
                        return {"ok": True, "results": hits, "truncated": True}
    if not hits:
        return {"ok": False, "error": f"nothing matching '{name}' in personal folders"}
    return {"ok": True, "results": hits}


@registry.tool(
    "Open a file or folder with its default application. Use the full path "
    "(e.g. from find_files).",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Full path"}},
        "required": ["path"],
    },
)
def open_path(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"path does not exist: {p}"}
    os.startfile(str(p))
    return {"ok": True, "message": f"opened {p.name}"}
