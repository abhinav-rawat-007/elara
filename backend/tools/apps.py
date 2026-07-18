"""Launching and closing Windows applications."""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import psutil

from .registry import registry

_START_MENU_DIRS = [
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]

# things people say -> what to actually launch
_ALIASES = {
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "settings": "ms-settings:",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "paint": "mspaint.exe",
}

_PROTECTED_PROCESSES = {
    "explorer.exe", "winlogon.exe", "csrss.exe", "services.exe",
    "lsass.exe", "svchost.exe", "system", "smss.exe", "wininit.exe",
    "dwm.exe", "ollama.exe", "python.exe", "elara.exe",
}


def _shortcut_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for base in _START_MENU_DIRS:
        if not base.exists():
            continue
        # Steam and some other launchers create .url shortcuts, not .lnk
        for pattern in ("*.lnk", "*.url"):
            for shortcut in base.rglob(pattern):
                index.setdefault(shortcut.stem.lower(), shortcut)
    return index


@registry.tool(
    "Open/launch an application on the PC by name, e.g. 'spotify', 'chrome', 'notepad'.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "App name as the user said it"}
        },
        "required": ["name"],
    },
)
def open_app(name: str) -> dict:
    query = name.strip().lower()
    alias = _ALIASES.get(query)
    if alias:
        os.startfile(alias)
        return {"ok": True, "message": f"opened {name}"}

    index = _shortcut_index()
    # exact -> substring -> fuzzy
    target = index.get(query)
    if target is None:
        subs = [k for k in index if query in k]
        if subs:
            target = index[min(subs, key=len)]
    if target is None:
        close = difflib.get_close_matches(query, list(index), n=1, cutoff=0.6)
        if close:
            target = index[close[0]]
    if target is None:
        return {
            "ok": False,
            "error": f"couldn't find an app matching '{name}'",
            "hint": "try the exact name from the Start Menu",
        }
    os.startfile(str(target))
    return {"ok": True, "message": f"opened {target.stem}"}


@registry.tool(
    "Close a running application by name, e.g. 'close spotify'.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "App name to close"}
        },
        "required": ["name"],
    },
)
def close_app(name: str) -> dict:
    query = name.strip().lower().removesuffix(".exe")
    if not query:
        return {"ok": False, "error": "no app name given"}

    # Match on the process's base name, preferring an exact hit. Only fall back
    # to a prefix match (e.g. "code" -> "code.exe") — a bare substring match
    # would let "chrome" also cull "chromedriver" or "code" cull "qcodemon".
    def base(pname: str) -> str:
        return (pname or "").lower().removesuffix(".exe")

    procs = list(psutil.process_iter(["name"]))
    names = {base(p.info["name"]) for p in procs if p.info["name"]}
    if query in names:
        matches = lambda b: b == query  # noqa: E731
    else:
        matches = lambda b: b.startswith(query)  # noqa: E731

    killed: list[str] = []
    for proc in procs:
        pname = (proc.info["name"] or "").lower()
        if pname in _PROTECTED_PROCESSES:
            continue
        if matches(base(pname)):
            try:
                proc.terminate()
                killed.append(proc.info["name"])
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
    if not killed:
        return {"ok": False, "error": f"no running app matching '{name}'"}
    return {"ok": True, "message": f"closed {', '.join(sorted(set(killed)))}"}
