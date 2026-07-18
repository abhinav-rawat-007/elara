"""Launching Steam games directly.

Steam's own UI is a Chromium web view that automation can't reliably drive, so
games launch through the steam:// URI protocol instead — instant, and Steam
starts itself first if it isn't running. The installed library is read from
Steam's own manifest files (libraryfolders.vdf + appmanifest_*.acf).
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path

from .registry import registry


def _steam_root() -> Path | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path, _ = winreg.QueryValueEx(key, "SteamPath")
        root = Path(path)
        if root.exists():
            return root
    except OSError:
        pass
    fallback = (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam"
    )
    return fallback if fallback.exists() else None


def parse_library_paths(vdf_text: str) -> list[Path]:
    """Library roots out of libraryfolders.vdf. VDF escapes backslashes."""
    return [
        Path(m.group(1).replace("\\\\", "\\"))
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf_text)
    ]


def parse_manifest(acf_text: str) -> tuple[str, str] | None:
    """(appid, name) out of an appmanifest_*.acf, or None if malformed."""
    appid = re.search(r'"appid"\s+"(\d+)"', acf_text)
    name = re.search(r'"name"\s+"([^"]+)"', acf_text)
    if appid and name:
        return appid.group(1), name.group(1).strip()
    return None


def _installed_games() -> dict[str, str]:
    """{lowercased game name -> appid} across every Steam library on disk."""
    root = _steam_root()
    if root is None:
        return {}
    lib_dirs = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for lib in parse_library_paths(vdf.read_text(encoding="utf-8", errors="ignore")):
            steamapps = lib / "steamapps"
            if steamapps not in lib_dirs:
                lib_dirs.append(steamapps)
    games: dict[str, str] = {}
    for lib in lib_dirs:
        if not lib.exists():
            continue
        for manifest in lib.glob("appmanifest_*.acf"):
            parsed = parse_manifest(
                manifest.read_text(encoding="utf-8", errors="ignore")
            )
            if parsed:
                appid, name = parsed
                games.setdefault(name.lower(), appid)
    games.pop("steamworks common redistributables", None)
    return games


@registry.tool(
    "Launch an installed Steam game by name, e.g. 'Marvel Rivals'. Starts Steam "
    "itself first if it isn't running. Use this instead of open_app for games.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Game name as the user said it"}
        },
        "required": ["name"],
    },
)
def launch_steam_game(name: str) -> dict:
    games = _installed_games()
    if not games:
        return {"ok": False, "error": "couldn't find a Steam library on this PC"}

    # exact -> substring -> fuzzy, same ladder as open_app
    query = name.strip().lower()
    appid = games.get(query)
    if appid is None:
        subs = [k for k in games if query in k]
        if subs:
            appid = games[min(subs, key=len)]
    if appid is None:
        close = difflib.get_close_matches(query, list(games), n=1, cutoff=0.6)
        if close:
            appid = games[close[0]]
    if appid is None:
        return {
            "ok": False,
            "error": f"no installed Steam game matching '{name}'",
            "installed": sorted(games)[:30],
        }
    matched = next(k for k, v in games.items() if v == appid)
    os.startfile(f"steam://rungameid/{appid}")
    return {"ok": True, "message": f"launching {matched} through Steam"}


@registry.tool("List the Steam games installed on this PC.")
def list_steam_games() -> dict:
    games = _installed_games()
    if not games:
        return {"ok": False, "error": "couldn't find a Steam library on this PC"}
    return {"ok": True, "games": sorted(games)}
