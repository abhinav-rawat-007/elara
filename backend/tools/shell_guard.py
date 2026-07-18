"""Risk classification for shell commands Elara is asked to run.

The model can call `run_powershell`, which is powerful enough to be dangerous
if a command slips through — a poisoned web page or a rogue local caller could
try to talk her into deleting files, pulling down a payload, or exfiltrating
data. We can't perfectly parse PowerShell, so this is defence in depth, not a
sandbox: any command that matches a risky pattern is held back until the user
confirms it out loud. The bar is deliberately low — a false "please confirm"
is cheap; a silent `Invoke-WebRequest ... | iex` is not.

`classify(command)` returns a short human reason if the command looks risky,
or None if it looks ordinary. Callers should refuse to run a risky command
until the user has explicitly confirmed.
"""

from __future__ import annotations

import re

# Each entry: (compiled pattern, why it's risky). Ordered roughly by how much
# damage the category can do, so the first match gives the most apt reason.
_RISKY: list[tuple[re.Pattern[str], str]] = [
    # Deleting or overwriting data
    (re.compile(r"\b(remove-item|rmdir|rd)\b|(?<!\w)\brm\b|(?<!\w)\bdel\b", re.I),
     "deletes files or folders"),
    (re.compile(r"\b(clear-content|set-content|out-file|add-content)\b", re.I),
     "overwrites file contents"),
    (re.compile(r"\bformat(-volume)?\b|\bdiskpart\b|\bcipher\b", re.I),
     "formats or wipes a disk"),
    # Power / process control
    (re.compile(r"\b(shutdown|restart-computer|stop-computer)\b", re.I),
     "shuts down or restarts the PC"),
    (re.compile(r"\b(stop-process|taskkill|kill)\b", re.I),
     "kills running processes"),
    (re.compile(r"\b(bcdedit|bootrec)\b", re.I),
     "changes boot configuration"),
    # Pulling code/data down from the network
    (re.compile(
        r"\b(invoke-webrequest|iwr|invoke-restmethod|irm|start-bitstransfer|"
        r"curl|wget|bitsadmin|certutil)\b", re.I),
     "downloads something from the internet"),
    (re.compile(r"\b(downloadstring|downloadfile|downloaddata)\b|net\.webclient",
                re.I),
     "downloads something from the internet"),
    # Executing arbitrary/obfuscated code
    (re.compile(r"\b(invoke-expression|iex)\b", re.I),
     "runs code built at runtime (Invoke-Expression)"),
    (re.compile(r"-enc(odedcommand)?\b|frombase64string", re.I),
     "runs an encoded/obfuscated command"),
    (re.compile(r"\b(set-executionpolicy)\b", re.I),
     "weakens the script execution policy"),
    # Persistence / system configuration
    (re.compile(r"\breg\b\s+(add|delete|import)|\b(new|remove|set)-itemproperty\b",
                re.I),
     "edits the Windows registry"),
    (re.compile(r"\b(schtasks|register-scheduledtask|new-scheduledtask)\b", re.I),
     "creates a scheduled task (persistence)"),
    (re.compile(r"\b(new-service|sc\.exe|set-service)\b", re.I),
     "installs or changes a Windows service"),
    (re.compile(r"\b(netsh|net\s+user|net\s+localgroup|add-localgroupmember)\b",
                re.I),
     "changes networking or user accounts"),
    (re.compile(r"\b(set-mppreference|add-mppreference)\b", re.I),
     "changes Windows Defender settings"),
]


def classify(command: str) -> str | None:
    """Return a short reason if `command` looks risky, else None."""
    if not command or not command.strip():
        return None
    for pattern, reason in _RISKY:
        if pattern.search(command):
            return reason
    return None


def is_risky(command: str) -> bool:
    return classify(command) is not None
