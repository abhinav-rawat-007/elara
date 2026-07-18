"""Controlling native Windows apps through UI Automation.

pywinauto's UIA backend reads an app's accessibility tree — actual buttons,
menus and fields by name — so Elara can work inside Spotify, Explorer or
Settings without vision. The flow mirrors the browser tools: inspect_window
hands out refs (w1, w2, …), click/type resolve them.

Threading: UIA/COM objects must stay on the thread that created them, and
asyncio.to_thread rotates pool threads — so every UIA call funnels through one
dedicated worker thread with COM initialized there.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from .registry import registry

log = logging.getLogger("elara.uia")

MAX_TREE_CHARS = 6000
MAX_ELEMENTS = 120
MAX_DEPTH = 4

# control names that get the confirm-first treatment, like risky PowerShell
_DESTRUCTIVE = re.compile(r"\b(delete|uninstall|remove|format|reset|erase)\b", re.I)


def _com_init() -> None:
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        log.debug("CoInitialize skipped", exc_info=True)


_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="elara-uia", initializer=_com_init
)

# refs from the most recent inspect_window; wrappers are only ever touched on
# the executor thread, so keeping them here is safe
_refs: dict[str, object] = {}


async def _run(fn, *args) -> dict:
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)


def _desktop():
    from pywinauto import Desktop

    return Desktop(backend="uia")


def _find_window(title: str):
    """Top-level window by fuzzy title — exact -> substring -> difflib."""
    wins = {w.window_text(): w for w in _desktop().windows() if w.window_text().strip()}
    q = title.strip().lower()
    for name, w in wins.items():
        if name.lower() == q:
            return w
    subs = [n for n in wins if q in n.lower()]
    if subs:
        return wins[min(subs, key=len)]
    lowered = {n.lower(): n for n in wins}
    close = difflib.get_close_matches(q, list(lowered), n=1, cutoff=0.6)
    return wins[lowered[close[0]]] if close else None


def _escape_keys(text: str) -> str:
    """type_keys treats +^%~(){} as commands — make user text literal."""
    return re.sub(r"([+^%~(){}])", r"{\1}", text).replace("\n", "{ENTER}")


def _no_window(title: str) -> dict:
    return {
        "ok": False,
        "error": f"no open window matching '{title}'",
        "hint": "call list_windows to see what's open",
    }


def _list_windows_sync() -> dict:
    names = sorted(
        {w.window_text().strip() for w in _desktop().windows() if w.window_text().strip()}
    )
    return {"ok": True, "windows": names}


def _focus_sync(title: str) -> dict:
    w = _find_window(title)
    if w is None:
        return _no_window(title)
    w.set_focus()
    return {"ok": True, "message": f"focused {w.window_text()}"}


def _inspect_sync(title: str, depth: int) -> dict:
    global _refs
    w = _find_window(title)
    if w is None:
        return _no_window(title)
    refs: dict[str, object] = {}
    lines: list[str] = []
    n = 0
    for el in w.descendants(depth=max(1, min(int(depth), MAX_DEPTH))):
        try:
            ctype = el.element_info.control_type or "Unknown"
            name = (el.window_text() or "").strip().replace("\n", " ")[:80]
        except Exception:
            continue
        # unnamed structural noise buries the useful controls
        if not name and ctype in ("Pane", "Group", "Custom", "Unknown", "Image"):
            continue
        n += 1
        if n > MAX_ELEMENTS:
            lines.append("…[more controls omitted — inspect deeper or by name]")
            break
        ref = f"w{n}"
        refs[ref] = el
        lines.append(f'[{ref}] {ctype} "{name}"')
    _refs = refs
    tree = "\n".join(lines)
    if len(tree) > MAX_TREE_CHARS:
        tree = tree[:MAX_TREE_CHARS] + "\n…[truncated]"
    return {"ok": True, "window": w.window_text(), "controls": tree}


def _click_ref_sync(ref: str, confirm: bool) -> dict:
    el = _refs.get(ref)
    if el is None:
        return {
            "ok": False,
            "error": f"unknown or stale ref '{ref}' — call inspect_window again",
        }
    try:
        name = (el.window_text() or "").strip()
    except Exception:
        return {"ok": False, "error": f"ref '{ref}' vanished — inspect_window again"}
    if _DESTRUCTIVE.search(name) and not confirm:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": f"Clicking '{name}' looks destructive. Ask the user to "
            "confirm, then retry with confirm=true.",
        }
    try:
        el.invoke()
    except Exception:
        el.click_input()
    return {"ok": True, "message": f"clicked {name or ref}"}


def _click_name_sync(window: str, name: str, confirm: bool) -> dict:
    w = _find_window(window)
    if w is None:
        return _no_window(window)
    q = name.strip().lower()
    candidates = []
    for el in w.descendants(depth=MAX_DEPTH):
        try:
            text = (el.window_text() or "").strip()
        except Exception:
            continue
        if text and q in text.lower():
            candidates.append((len(text), el, text))
    if not candidates:
        return {
            "ok": False,
            "error": f"no control named like '{name}' in {w.window_text()}",
            "hint": "inspect_window shows what's actually there",
        }
    _len, el, text = min(candidates, key=lambda c: c[0])
    if _DESTRUCTIVE.search(text) and not confirm:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": f"Clicking '{text}' looks destructive. Ask the user to "
            "confirm, then retry with confirm=true.",
        }
    try:
        el.invoke()
    except Exception:
        el.click_input()
    return {"ok": True, "message": f"clicked {text}"}


def _type_sync(text: str, ref: str | None) -> dict:
    # element.type_keys is silently swallowed by modern controls (Win11
    # Notepad's document, for one) — click to place the caret, then send real
    # keystrokes; fall back to the UIA ValuePattern if the click won't land.
    import time

    from pywinauto.keyboard import send_keys

    keys = _escape_keys(text)
    if ref:
        el = _refs.get(ref)
        if el is None:
            return {
                "ok": False,
                "error": f"unknown or stale ref '{ref}' — call inspect_window again",
            }
        try:
            el.click_input()
            time.sleep(0.4)  # typing before focus settles drops characters
            send_keys(keys, with_spaces=True, pause=0.04)
        except Exception:
            el.iface_value.SetValue(text)
    else:
        time.sleep(0.4)
        send_keys(keys, with_spaces=True, pause=0.04)
    return {"ok": True, "message": f"typed {len(text)} characters"}


def _read_sync(title: str) -> dict:
    w = _find_window(title)
    if w is None:
        return _no_window(title)
    parts: list[str] = []
    for el in w.descendants(depth=MAX_DEPTH):
        try:
            text = (el.window_text() or "").strip()
        except Exception:
            continue
        if text and text not in parts[-3:]:
            parts.append(text)
        if sum(len(p) for p in parts) > MAX_TREE_CHARS:
            break
    return {"ok": True, "window": w.window_text(), "text": "\n".join(parts)[:MAX_TREE_CHARS]}


@registry.tool(
    "List the titles of every open window on the PC. Start here when working "
    "inside a native app.",
    timeout=90.0,
)
async def list_windows() -> dict:
    return await _run(_list_windows_sync)


@registry.tool(
    "Bring a window to the front by (fuzzy) title, e.g. 'spotify'.",
    {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "Window title"}},
        "required": ["title"],
    },
    timeout=90.0,
)
async def focus_window(title: str) -> dict:
    return await _run(_focus_sync, title)


@registry.tool(
    "See the buttons, fields and menus inside a window, each with a ref "
    "(w1, w2, …) for click_control / type_text. Slow on huge windows — keep "
    "depth small and re-inspect after the window changes.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Window title (fuzzy)"},
            "depth": {"type": "integer", "description": "Tree depth 1-4, default 3"},
        },
        "required": ["title"],
    },
    timeout=90.0,
)
async def inspect_window(title: str, depth: int = 3) -> dict:
    return await _run(_inspect_sync, title, depth)


@registry.tool(
    "Click a control inside a window by its ref from inspect_window. For "
    "destructive-looking controls (delete, uninstall…) ask the user first, "
    "then retry with confirm=true.",
    {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Control ref, e.g. 'w7'"},
            "confirm": {"type": "boolean", "description": "true after the user approved"},
        },
        "required": ["ref"],
    },
    timeout=90.0,
)
async def click_control(ref: str, confirm: bool = False) -> dict:
    return await _run(_click_ref_sync, ref, confirm)


@registry.tool(
    "Click a control inside a window by its visible name — a shortcut when "
    "you already know the button's label and don't need a full inspect.",
    {
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "Window title (fuzzy)"},
            "name": {"type": "string", "description": "Control label, e.g. 'Play'"},
            "confirm": {"type": "boolean", "description": "true after the user approved"},
        },
        "required": ["window", "name"],
    },
    timeout=90.0,
)
async def click_control_by_name(window: str, name: str, confirm: bool = False) -> dict:
    return await _run(_click_name_sync, window, name, confirm)


@registry.tool(
    "Type text into a native app — into a specific control (ref from "
    "inspect_window) or into whatever has keyboard focus. Never used for "
    "passwords; the user types those personally.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
            "ref": {"type": "string", "description": "Optional control ref, e.g. 'w4'"},
        },
        "required": ["text"],
    },
    timeout=90.0,
)
async def type_text(text: str, ref: str | None = None) -> dict:
    return await _run(_type_sync, text, ref)


@registry.tool(
    "Read the visible text inside a window — labels, list items, messages.",
    {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "Window title (fuzzy)"}},
        "required": ["title"],
    },
    timeout=90.0,
)
async def read_window(title: str) -> dict:
    return await _run(_read_sync, title)
