"""Keeps Ollama alive for Elara.

If nothing is answering on the configured (local) Ollama host, this spawns
`ollama serve` as a hidden child process and ties it to the backend's lifetime
with a Windows Job Object (kill-on-close): however the backend dies — tray
Quit, crash, task manager — the OS kills the Ollama we started along with it.
An Ollama the user started themselves is left alone.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("elara.ollama")

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_job = None  # job handle must stay referenced as long as the backend lives

START_TIMEOUT_S = 12.0


def _healthy(host: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=timeout):
            return True
    except Exception:
        return False


def _find_ollama() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    local = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return str(local) if local.exists() else None


def _assign_to_kill_on_close_job(proc: subprocess.Popen):
    """Put `proc` in a Job Object that dies when this process's handle closes."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
    return job


def ensure_ollama(host: str) -> bool:
    """Make sure Ollama answers on `host`; start it ourselves if we can.

    Blocking (polls for up to START_TIMEOUT_S) — call off the event loop.
    Returns True once healthy.
    """
    if "127.0.0.1" not in host and "localhost" not in host:
        return _healthy(host)  # remote ollama is not ours to manage

    global _proc, _job
    with _lock:
        if _healthy(host):
            return True
        if _proc is None or _proc.poll() is not None:
            exe = _find_ollama()
            if not exe:
                log.warning("ollama is not running and I can't find ollama.exe")
                return False
            log.info("starting ollama: %s serve", exe)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            _proc = subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            _job = _assign_to_kill_on_close_job(_proc)

        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if _healthy(host, timeout=0.5):
                log.info("ollama is up")
                return True
            if _proc.poll() is not None:
                log.warning("ollama exited right away (code %s)", _proc.returncode)
                return False
            time.sleep(0.25)
        log.warning("ollama did not become healthy within %ss", START_TIMEOUT_S)
        return False
