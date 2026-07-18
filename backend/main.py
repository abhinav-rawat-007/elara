"""Elara backend — FastAPI WebSocket server wiring brain + voice + tools.

Run:  python -m backend.main       (from D:\\Work\\elara)
   or python main.py               (from D:\\Work\\elara\\backend)

Client <-> server JSON protocol (over ws://127.0.0.1:8765/ws):

  client -> server:
    {type: "user_text", text}          user typed/said something
    {type: "ptt", action: "start"}     push-to-talk pressed  -> begin recording
    {type: "ptt", action: "stop"}      push-to-talk released -> transcribe + run
    {type: "interrupt"}                stop Elara speaking
    {type: "get_config"} / {type: "set_config", config}
    {type: "reset"}                    clear conversation

  server -> client:
    {type: "assistant_start"|"assistant_delta"|"assistant_done", id, text}
    {type: "tool_event", name, status, detail}
    {type: "status", state: "idle"|"listening"|"thinking"|"speaking"}
    {type: "transcript", text}         what STT heard (echoed as the user bubble)
    {type: "config", config}
    {type: "error", message}
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

# allow running both as `python -m backend.main` and `python main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend import security  # noqa: E402
from backend.config import VOICE, Config  # noqa: E402
from backend.brain.agent import Agent  # noqa: E402
from backend.brain import claude_code  # noqa: E402
from backend.brain.provider import AnthropicProvider, OllamaProvider  # noqa: E402
from backend.memory import Memory  # noqa: E402
from backend.tools import registry  # noqa: E402
from backend.tools.registry import ToolContext  # noqa: E402
from backend.tools.memory_tools import bind_memory  # noqa: E402
from backend.voice.stt import Recorder, Transcriber  # noqa: E402
from backend.voice.tts import Speaker, warm_up as tts_warm_up  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("elara")

HOST, PORT = "127.0.0.1", 8765

app = FastAPI(title="Elara")
# The server binds to loopback only, but a wide-open CORS policy would still let
# any website the user visits read /health and probe the port. Scope it to the
# same origins the WebSocket trusts.
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(security.allowed_origins()),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

config = Config.load()
recorder = Recorder()
transcriber = Transcriber(config.stt_model)
memory = Memory()
bind_memory(memory)


def _cloud_provider():
    """The cloud brain, if configured — None means Elara stays fully local.

    Backend order: the user's Claude subscription (via the local Claude Code
    install — no per-token cost) is preferred, an API key is the fallback.
    `cloud_backend` in config pins one explicitly.
    """
    if config.cloud_mode == "never":
        return None
    want = config.cloud_backend
    if want in ("auto", "subscription") and claude_code.available():
        if want == "subscription" or claude_code.cli_on_path() or not config.anthropic_api_key:
            log.info("cloud brain: Claude subscription (claude code)")
            return claude_code.ClaudeCodeProvider()
    if want in ("auto", "api") and config.anthropic_api_key:
        try:
            log.info("cloud brain: Anthropic API (%s)", config.cloud_model)
            return AnthropicProvider(config.anthropic_api_key, config.cloud_model)
        except Exception:
            log.warning("cloud provider unavailable", exc_info=True)
    return None


class Session:
    """One connected UI client."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.provider = OllamaProvider(config.model, config.ollama_host)
        self.agent = Agent(
            self.provider,
            registry,
            config.user_name,
            memory,
            cloud_provider=_cloud_provider(),
            cloud_mode=config.cloud_mode,
        )
        self.speaker = Speaker(
            emit=self.emit,
            get_voice=lambda: VOICE,
            is_enabled=lambda: config.speak_replies,
        )
        # Tools reach back into *this* session (to speak, to emit) through a
        # per-session context, installed on the running task via bind() — never
        # a shared global, which would cross wires between two connections.
        self.ctx = ToolContext(speak=self.speak, emit=self.emit)
        self._turn_lock = asyncio.Lock()
        # proactive speech: she may pipe up after a lull, once per quiet stretch
        self.last_activity = time.monotonic()
        self._proactive_armed = True
        self.idle_task: asyncio.Task | None = None

    def bind(self) -> None:
        """Make this session the active tool context for the current task."""
        registry.bind_context(self.ctx)

    def touch(self) -> None:
        """Note user activity — restarts the idle countdown and re-arms her."""
        self.last_activity = time.monotonic()
        self._proactive_armed = True

    async def emit(self, event: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(event, default=str))
        except Exception:
            # Usually just a closed socket mid-turn; log quietly so real
            # serialization bugs still surface under debug logging.
            log.debug("emit failed for %s", event.get("type"), exc_info=True)

    async def speak(self, text: str, emotion: str = "neutral") -> None:
        await self.speaker.say(text, emotion)

    async def handle_user_text(self, text: str) -> None:
        self.bind()
        text = (text or "").strip()
        if not text:
            return
        if self._turn_lock.locked():
            self.speaker.interrupt()
            self.agent.cancel()  # stop the turn in flight, not just its speech
        async with self._turn_lock:
            await self.emit({"type": "status", "state": "thinking"})
            try:
                await self.agent.run_turn(text, self.emit, self.speak)
            except Exception as exc:
                log.exception("turn failed")
                await self.emit(
                    {"type": "error", "message": f"My brain hiccuped: {exc}"}
                )
            finally:
                if not self.speaker.speaking:
                    await self.emit({"type": "status", "state": "idle"})
                self.touch()  # idle countdown starts when the turn ends

    async def idle_watch(self) -> None:
        """Proactive speech: after a quiet stretch she says one unprompted,
        in-character line. One nudge per lull — user activity re-arms her."""
        self.bind()
        while True:
            await asyncio.sleep(20)
            if not (config.proactive and self._proactive_armed):
                continue
            if time.monotonic() - self.last_activity < config.proactive_minutes * 60:
                continue
            if self._turn_lock.locked() or self.speaker.speaking:
                continue
            self._proactive_armed = False
            async with self._turn_lock:
                await self.emit({"type": "status", "state": "thinking"})
                try:
                    await self.agent.run_proactive(self.emit, self.speak)
                except Exception:
                    log.exception("proactive turn failed")
                finally:
                    if not self.speaker.speaking:
                        await self.emit({"type": "status", "state": "idle"})

    async def handle_ptt(self, action: str) -> None:
        self.bind()
        if action == "start":
            self.speaker.interrupt()
            recorder.start()
            await self.emit({"type": "status", "state": "listening"})
            asyncio.create_task(self._stream_levels())
        elif action == "stop":
            audio = recorder.stop()
            await self.emit({"type": "status", "state": "thinking"})
            # run transcription + the turn off the receive loop so the next
            # ptt press / interrupt is handled immediately, not queued
            asyncio.create_task(self._transcribe_and_run(audio))

    async def _transcribe_and_run(self, audio) -> None:
        self.bind()
        text = await asyncio.to_thread(transcriber.transcribe, audio)
        text = text.strip()
        if not text:
            await self.emit({"type": "status", "state": "idle"})
            await self.emit(
                {"type": "error", "message": "I didn't catch that."}
            )
            return
        await self.emit({"type": "transcript", "text": text})
        await self.handle_user_text(text)

    async def _stream_levels(self) -> None:
        while recorder.recording:
            await self.emit({"type": "mic_level", "level": recorder.level})
            await asyncio.sleep(0.05)

    async def send_config(self) -> None:
        await self.emit(
            {"type": "config", "config": config.as_dict()}
        )

    async def send_history(self) -> None:
        msgs = [
            m
            for m in memory.recent_messages(20)
            if m["role"] in ("user", "assistant") and m["content"].strip()
        ]
        if msgs:
            await self.emit({"type": "history", "messages": msgs})


@app.get("/health")
async def health(request: Request):
    # `authorized` lets a newly launched backend tell whether an instance
    # already on this port shares its token — i.e. whether the current UI could
    # actually use it — so it can defer to a compatible one and take over a
    # stale one instead of silently leaving Elara mute. See _existing_instance.
    origin = request.headers.get("origin")
    token = request.query_params.get("token")
    return {
        "ok": True,
        "model": config.model,
        "authorized": security.authorize(origin, token),
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    token = ws.query_params.get("token")
    if not security.authorize(origin, token):
        # Reject the handshake outright — an unauthorized page/process never
        # gets a session, so it can never reach a tool.
        log.warning("rejected ws connection from origin %r", origin)
        await ws.close(code=1008)  # policy violation
        return

    await ws.accept()
    session = Session(ws)
    session.bind()  # this connection's tasks inherit its tool context
    session.speaker.start()
    session.idle_task = asyncio.create_task(session.idle_watch())
    await session.send_config()
    await session.send_history()
    log.info("UI connected")

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            kind = msg.get("type")
            session.touch()

            if kind == "user_text":
                asyncio.create_task(session.handle_user_text(msg.get("text", "")))
            elif kind == "ptt":
                await session.handle_ptt(msg.get("action", ""))
            elif kind == "interrupt":
                session.speaker.interrupt()
                await session.emit({"type": "status", "state": "idle"})
            elif kind == "reset":
                session.agent.reset()
            elif kind == "get_config":
                await session.send_config()
            elif kind == "set_config":
                # Coerce/validate each field: an unauthenticated dev-mode client
                # (or a buggy one) must not be able to poke a string into
                # proactive_minutes and wedge the idle loop.
                config.apply_patch(msg.get("config") or {})
                config.save()
                # a newly pasted API key / mode change takes effect immediately
                session.agent.cloud_provider = _cloud_provider()
                session.agent.cloud_mode = config.cloud_mode
                await session.send_config()
    except WebSocketDisconnect:
        log.info("UI disconnected")
    except Exception:
        log.exception("websocket error")
    finally:
        if session.idle_task:
            session.idle_task.cancel()


def _existing_instance() -> str | None:
    """Classify a backend already holding the port, from our token's point of view.

    Returns:
      None           — nothing healthy there; we should bind.
      "compatible"   — it accepts our token (or we have none, a dev launch), so
                       the current UI can use it and we can safely bow out.
      "incompatible" — it enforces a different token (a stale orphan from an
                       earlier launch). Our webview holds a token it will reject,
                       so deferring would leave Elara mute.

    The distinction is what stops the silent-mute bug: the Tauri shell mints a
    fresh token each launch, and an orphaned prior backend still on the port
    would reject the new UI. See security.authorize and /health's `authorized`.
    """
    import urllib.request

    token = security.expected_token()
    url = f"http://{HOST}:{PORT}/health"
    if token:
        url += f"?token={token}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    if data.get("ok") is not True:
        return None
    # A token-less (manual dev) launch has nothing to mismatch — always defer.
    if not token:
        return "compatible"
    return "compatible" if data.get("authorized") else "incompatible"


def _take_over_port() -> bool:
    """Terminate whatever process is listening on our port so we can bind.

    Only used against a stale, token-incompatible Elara instance — one the
    current UI cannot use. Best-effort; returns True once the port is free.
    """
    try:
        import psutil
    except Exception:
        return False

    victims = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if (
                conn.laddr
                and conn.laddr.port == PORT
                and conn.status == psutil.CONN_LISTEN
                and conn.pid
            ):
                victims.append(conn.pid)
    except Exception:
        # net_connections can raise on locked-down systems — nothing we can do
        return False

    for pid in set(victims):
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # confirm the port actually came free before we try to bind
    for _ in range(15):
        if _existing_instance() is None:
            return True
        time.sleep(0.2)
    return _existing_instance() is None


def _warm_up():
    """Boot Ollama and preload the whisper + Kokoro models at startup."""
    try:
        from backend.brain.ollama_boot import ensure_ollama

        ensure_ollama(config.ollama_host)
    except Exception as exc:
        log.warning("ollama boot skipped: %s", exc)
    try:
        transcriber.warm_up()
    except Exception as exc:
        log.warning("whisper warm-up skipped: %s", exc)
    try:
        tts_warm_up(VOICE)
    except Exception as exc:
        log.warning("kokoro warm-up skipped: %s", exc)


if __name__ == "__main__":
    import uvicorn

    existing = _existing_instance()
    if existing == "compatible":
        log.info("another Elara backend already owns port %d, deferring to it", PORT)
        sys.exit(0)
    if existing == "incompatible":
        # A stale backend from an earlier launch holds the port with a token our
        # UI can't present. Deferring would mute Elara, so take the port instead.
        log.warning(
            "a stale Elara backend owns port %d with a different token; "
            "the UI can't use it — taking over",
            PORT,
        )
        if not _take_over_port():
            log.error(
                "couldn't free port %d from the stale backend; exiting so it "
                "keeps serving rather than leaving two half-broken instances",
                PORT,
            )
            sys.exit(1)
    threading.Thread(target=_warm_up, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
