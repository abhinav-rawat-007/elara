# Elara

A Jarvis-style AI companion for Windows. Talk to her by voice or text, and she
answers back in a natural voice and actually *does* things — opens apps, launches
Steam games, drives her own browser to research and compare things for you, works
inside native apps, searches the web, controls volume and media, finds files, and more.

Runs entirely on your machine for **$0**, fully offline: a local LLM (Ollama),
local speech recognition (faster-whisper), and a local neural voice (Kokoro).
Optionally add an Anthropic API key and she gains a **hybrid brain**: everyday
chat stays local and free, while big multi-step tasks escalate to Claude.

## Architecture

```
Tauri 2 + React (HUD)  ──WebSocket──►  Python backend  ──HTTP──►  Ollama (qwen3:8b)
  animated orb, chat                     FastAPI + tools
  push-to-talk                           STT (whisper) + TTS (kokoro)
```

- **Frontend** — React 19 + TypeScript, Tailwind CSS v4, shadcn/ui, Framer Motion
- **Shell** — Tauri 2 (Rust) — spawns the backend, global hotkey, window
- **Backend** — Python 3.12 / FastAPI — the brain, voice, and tools
- **Brain** — Ollama `qwen3:8b` (swappable via `backend/brain/provider.py`)
- **Voice out** — Kokoro-82M via kokoro-onnx (`af_heart` by default, runs offline on CPU)
- **Voice in** — faster-whisper `small` (GPU with CPU fallback)

## Prerequisites

- [Ollama](https://ollama.com) installed, with the model pulled: `ollama pull qwen3:8b`
  (Elara starts and stops the Ollama server herself — it just needs to be installed)
- Python 3.11+ and the backend venv (see below)
- Node 18+ and [pnpm](https://pnpm.io); Rust stable (for the Tauri build)

## Setup

```powershell
# Frontend deps
pnpm install

# Backend deps
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..

# Kokoro TTS model files (~340 MB, one time)
mkdir backend\models\kokoro
curl.exe -L -o backend\models\kokoro\kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl.exe -L -o backend\models\kokoro\voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

## Run

The Tauri shell auto-starts the Python backend for you:

```powershell
pnpm tauri dev
```

Or run the pieces separately (useful while developing the UI):

```powershell
# terminal 1 — backend
cd backend; .\.venv\Scripts\python.exe main.py

# terminal 2 — frontend
pnpm dev        # then open http://localhost:1420
```

## Using her

- **Type** in the box, or **hold `Space`** (or the mic button) to talk, release to send.
- Press the mic **while she's speaking** to interrupt and cut in.
- `Ctrl+Alt+E` brings the window to the front from anywhere.
- The **minimize icon** shrinks her to a floating always-on-top **mini orb** (drag it anywhere; click the expand icon to restore the full HUD). Push-to-talk still works in mini mode.
- **Closing the window hides her to the system tray** instead of quitting — click the tray icon to bring her back, or right-click it for Show / Quit.
- The gear opens settings: pick her voice, toggle spoken replies, **launch on startup**, and set your name.

### She remembers

Elara has a persistent memory backed by SQLite (`backend/elara.db`):

- **Conversation history** is restored when you reopen her.
- **Facts about you** — tell her "remember that…" and she stores it (she decides when
  something's worth keeping), then recalls it in future conversations. Ask her to
  "forget…" to remove it. "New conversation" (the ↺ icon) clears history but keeps facts.

### Things to try

- "What can you see about the weather in Delhi right now?"
- "Open Spotify."
- "Set the volume to 30 percent."
- "Take a screenshot."
- "Find my resume."
- "Launch Marvel Rivals." *(any installed Steam game, by name)*
- "Go to Amazon, compare a few 27-inch gaming monitors and tell me which to get."
  *(needs the cloud brain — see below)*
- "Open Notepad and type a haiku in it."

### The hybrid brain (optional, for complex tasks)

The local model is great at chat and single actions, but long multi-step tasks
(browsing + comparing, driving an app step by step) need more horsepower. When
she judges a task needs it, Elara escalates *herself*: she calls
`enter_focus_mode` and the rest of that turn runs on Claude with a much larger
step budget. Casual conversation never leaves your machine.

Two ways to power focus mode (Settings → "Cloud brain source"):

- **Claude subscription** (preferred, no extra cost) — if
  [Claude Code](https://claude.com/claude-code) is installed and logged in with
  your Pro/Max account, focus tasks run through the Claude Agent SDK on your
  subscription. Elara's own guarded tools are mounted into the session; Claude
  Code's write/shell tools are disabled. Uses your plan's normal usage limits.
- **Anthropic API key** — pay-as-you-go via
  [console.anthropic.com](https://console.anthropic.com); paste the key into
  Settings.

- **Auto** (default) — subscription if available, else the API key.
- **Cloud mode Always / Never** — force cloud on or off entirely.
- Neither configured? Everything still works, minus the marathon tasks.

### Her browser and app control

- **Her own browser** — a visible Chrome/Edge window (separate profile, her own
  cookies) she navigates, reads, clicks and types in. Watch her work.
- **Native apps** — she reads an app's actual buttons and menus through Windows
  UI Automation and clicks them by name.
- **Steam** — games launch instantly via `steam://` using your installed library
  (no fragile UI clicking).

## Project layout

```
src/                 React UI (Orb, ChatPanel, SettingsDialog, useElara hook)
src-tauri/           Rust shell (spawns backend, mints auth token, global hotkey)
backend/
  main.py            FastAPI WebSocket server
  security.py        WebSocket auth (token + Origin allow-list)
  paths.py           dev vs. frozen-sidecar file locations
  memory.py          SQLite: history, learned facts, rolling summary
  brain/             providers (Ollama + Claude), agent (tool loop + escalation), streaming, personality
  voice/             stt (whisper), tts (kokoro)
  tools/             apps, steam, browser, uia, websearch, system, files, memory_tools, guards
  tests/             pytest suite (pure logic + agent loop)
```

## Security model

The backend can open apps, run PowerShell, and read files, so the WebSocket it
listens on is not left open:

- **Per-launch token.** The Tauri shell mints a random token, passes it to the
  Python backend (`ELARA_TOKEN`) and to the webview (via the `backend_token`
  command). The UI presents it as `?token=…`; without it, connections are
  refused. This stops any other local process from driving Elara.
- **Origin allow-list.** In plain-browser dev (no token), only the Tauri and
  Vite origins are accepted, so a random website can't reach `ws://127.0.0.1`.
- **PowerShell guard.** `run_powershell` refuses — pending an explicit,
  spoken confirmation — any command that deletes, downloads, runs generated
  code, or changes system settings (see `backend/tools/shell_guard.py`).
- **Browser guard.** She *never* types into password/payment fields (hard
  refusal — you type those yourself), and purchase/checkout-shaped clicks are
  held for your confirmation (see `backend/tools/browser_guard.py`). The same
  confirm-first treatment applies to destructive-looking controls in native
  apps (delete, uninstall, reset…).
- **Privacy note.** With a cloud key set, escalated turns send the conversation
  and tool results (page text, window text) to the Anthropic API. Casual chat
  and everything in `cloud_mode: never` stays local.
- A tightened Content-Security-Policy is set in `tauri.conf.json`.

## Tests

```powershell
# backend (pytest)
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # once
cd ..
backend\.venv\Scripts\python.exe -m pytest

# frontend (vitest)
pnpm test
```

## Packaging as a standalone app

`pnpm tauri dev` runs the backend straight from the venv — no extra steps. For a
distributable build, the Python backend is frozen into a sidecar exe so the app
runs on machines without Python:

```powershell
.\scripts\build-sidecar.ps1     # builds backend/dist/elara-backend.exe and
                                 # stages it under src-tauri/binaries/
```

Then add the sidecar to `src-tauri/tauri.conf.json` and build:

```jsonc
"bundle": { "externalBin": ["binaries/elara-backend"], ... }
```

```powershell
pnpm tauri build
```

The shell prefers a bundled `elara-backend.exe` next to the app and falls back
to the venv in dev, so both paths keep working. When frozen, config and the DB
live in `%APPDATA%\Elara`, and the Kokoro model download goes to
`%APPDATA%\Elara\models\kokoro`.

## Notes & limits

- An 8B local model is great at chat and simple tool calls but will occasionally
  fumble complex multi-step tasks — that's what the hybrid brain is for. Without
  a key she'll try locally and be honest when she can't manage.
- Her browser prefers your installed Chrome/Edge (launched with a separate
  profile). If neither exists she downloads Playwright's Chromium on first use.
- Some sites fight automation (CAPTCHAs, bot checks); she'll tell you when a
  site blocks her instead of pretending.
- Her voice (Kokoro) is fully offline; the one-time ~340 MB model download in
  Setup is all it needs. Only web search requires an internet connection.
- If Ollama isn't running, Elara starts it in the background and shuts it down
  again when she quits (an Ollama you started yourself is left alone).
- Risky shell commands (delete, download, run code, change system settings)
  require confirmation before they run.
- As she learns more about you, only the facts relevant to the moment are put in
  front of the model, and long conversations are folded into a rolling summary —
  so context stays lean without her forgetting.
