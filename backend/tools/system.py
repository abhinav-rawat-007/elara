"""System control: volume, brightness, media keys, screenshots, status, commands."""

from __future__ import annotations

import asyncio
import ctypes
import datetime as dt
import os
import subprocess
from pathlib import Path

import psutil

from . import shell_guard
from .registry import registry

_SCREENSHOT_DIR = Path.home() / "Pictures" / "Elara"


def _volume_interface():
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


@registry.tool(
    "Set the PC speaker volume to a level from 0 to 100.",
    {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume 0-100"}
        },
        "required": ["level"],
    },
)
def set_volume(level: int) -> dict:
    level = max(0, min(100, int(level)))
    _volume_interface().SetMasterVolumeLevelScalar(level / 100.0, None)
    return {"ok": True, "message": f"volume set to {level}%"}


@registry.tool(
    "Control media playback or audio: play_pause, next, previous, mute, unmute.",
    {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play_pause", "next", "previous", "mute", "unmute"],
            }
        },
        "required": ["action"],
    },
)
def media_control(action: str) -> dict:
    if action in ("mute", "unmute"):
        _volume_interface().SetMute(1 if action == "mute" else 0, None)
        return {"ok": True, "message": f"audio {action}d"}
    import pyautogui

    key = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack"}[action]
    pyautogui.press(key)
    return {"ok": True, "message": f"media {action} sent"}


@registry.tool(
    "Set the laptop screen brightness from 0 to 100.",
    {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Brightness 0-100"}
        },
        "required": ["level"],
    },
)
def set_brightness(level: int) -> dict:
    import screen_brightness_control as sbc

    level = max(0, min(100, int(level)))
    sbc.set_brightness(level)
    return {"ok": True, "message": f"brightness set to {level}%"}


@registry.tool("Take a screenshot of the screen and open it.")
def take_screenshot() -> dict:
    import pyautogui

    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCREENSHOT_DIR / f"screenshot_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    pyautogui.screenshot(str(path))
    os.startfile(str(path))
    return {"ok": True, "message": f"screenshot saved to {path}"}


@registry.tool("Lock the PC (Windows lock screen).")
def lock_pc() -> dict:
    ctypes.windll.user32.LockWorkStation()
    return {"ok": True, "message": "PC locked"}


@registry.tool(
    "Get current system status: time, battery, CPU, RAM and disk usage."
)
def get_system_status() -> dict:
    battery = psutil.sensors_battery()
    disk = psutil.disk_usage("C:\\")
    return {
        "ok": True,
        "time": dt.datetime.now().strftime("%A %I:%M %p, %B %d %Y"),
        "battery_percent": battery.percent if battery else None,
        "plugged_in": battery.power_plugged if battery else None,
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_c_free_gb": round(disk.free / 1e9, 1),
    }


@registry.tool(
    "Set a timer. Elara will announce out loud when it finishes.",
    {
        "type": "object",
        "properties": {
            "minutes": {"type": "number", "description": "Duration in minutes"},
            "label": {"type": "string", "description": "What the timer is for"},
        },
        "required": ["minutes"],
    },
)
async def set_timer(minutes: float, label: str = "") -> dict:
    # Capture the calling session's context now, so a timer set in one window
    # still speaks through that window even if another connects later.
    ctx = registry.context()

    async def _ring():
        await asyncio.sleep(max(1.0, float(minutes) * 60))
        if ctx.speak:
            what = f" for {label}" if label else ""
            await ctx.speak(f"Heads up — your {minutes:g} minute timer{what} is done.")

    asyncio.get_running_loop().create_task(_ring())
    return {"ok": True, "message": f"timer set for {minutes:g} minutes"}


@registry.tool(
    "Run a PowerShell command on the PC and return its output. For risky commands "
    "(deleting, downloading, running code, changing system settings), first ask the "
    "user to confirm out loud, then call again with confirm=true.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "PowerShell command"},
            "confirm": {
                "type": "boolean",
                "description": "true only after the user verbally confirmed a risky command",
            },
        },
        "required": ["command"],
    },
)
def run_powershell(command: str, confirm: bool = False) -> dict:
    risk = shell_guard.classify(command)
    if risk and not confirm:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": f"This command {risk}. Tell the user exactly what it will do, "
            "get their confirmation, then retry with confirm=true.",
        }
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "command timed out after 30s"}
    out = (proc.stdout or "").strip()[:2000]
    err = (proc.stderr or "").strip()[:800]
    return {"ok": proc.returncode == 0, "output": out, "stderr": err}
