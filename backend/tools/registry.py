"""Tool registry: exposes python functions to the LLM as callable tools."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolContext:
    """Runtime hooks tools may need, scoped to the session that is running.

    A single global would break the moment two UI clients connect (or one
    reconnects): a timer started in one window would fire through whichever
    session bound itself last. Instead each session installs its own context
    into `_current_ctx` for the duration of its turn (see Registry.context),
    and asyncio copies that context into any task a tool spawns — so a timer
    keeps talking to the window that set it.
    """

    speak: Callable | None = None  # async fn(str) — make Elara say something
    emit: Callable | None = None  # async fn(dict) — push an event to the UI


# The context of the session currently running. asyncio.create_task and
# asyncio.to_thread both copy the active contextvars, so tools (and the tasks
# they spawn, like a timer) see the right session without any global mutation.
_current_ctx: contextvars.ContextVar[ToolContext] = contextvars.ContextVar(
    "elara_tool_ctx", default=ToolContext()
)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    timeout: float | None = None  # per-tool override of TOOL_TIMEOUT_S


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    @staticmethod
    def bind_context(ctx: ToolContext) -> None:
        """Install `ctx` as the active session context for this task/turn.

        Call at the top of each per-session coroutine (turn, ptt, proactive).
        Because asyncio gives each task its own copy of the contextvars, this
        never leaks into a different session's concurrent work.
        """
        _current_ctx.set(ctx)

    @staticmethod
    def context() -> ToolContext:
        """The context of the session currently running this code."""
        return _current_ctx.get()

    def tool(
        self,
        description: str,
        parameters: dict | None = None,
        timeout: float | None = None,
    ):
        """Decorator: register a function as an LLM-callable tool.

        `timeout` overrides TOOL_TIMEOUT_S for slow tools (browser navigation,
        UIA tree walks) without loosening the default for everything else."""

        def wrap(func: Callable) -> Callable:
            schema = parameters or {"type": "object", "properties": {}}
            self._tools[func.__name__] = Tool(
                name=func.__name__,
                description=description,
                parameters=schema,
                func=func,
                timeout=timeout,
            )
            return func

        return wrap

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    # A hung tool (stalled network call, wedged process) must never freeze her
    # turn forever — time out and let the model tell the user what happened.
    TOOL_TIMEOUT_S = 45.0

    async def execute(self, name: str, args: dict[str, Any]) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        if not isinstance(args, dict):
            args = {}
        # drop hallucinated kwargs the function doesn't accept
        sig = inspect.signature(tool.func)
        accepted = {
            k: v for k, v in args.items() if k in sig.parameters
        }
        if inspect.iscoroutinefunction(tool.func):
            coro = tool.func(**accepted)
        else:
            coro = asyncio.to_thread(tool.func, **accepted)
        timeout = tool.timeout if tool.timeout is not None else self.TOOL_TIMEOUT_S
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": f"{name} timed out after {int(timeout)} seconds",
            }
        if not isinstance(result, dict):
            result = {"ok": True, "message": str(result)}
        return result


registry = Registry()
