"""Tools for Elara's long-term memory of facts about the user."""

from __future__ import annotations

from .registry import registry

# Set by main.py once the Memory instance exists.
_memory = None


def bind_memory(memory) -> None:
    global _memory
    _memory = memory


@registry.tool(
    "Remember a durable fact about the user (a preference, a person, a project, a "
    "routine) so you recall it in future conversations. Use short, self-contained facts.",
    {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact to remember, e.g. 'Prefers dark mode' or "
                "'Works as a game developer'.",
            }
        },
        "required": ["fact"],
    },
)
def remember_fact(fact: str) -> dict:
    if _memory is None:
        return {"ok": False, "error": "memory not available"}
    _memory.add_fact(fact)
    return {"ok": True, "message": f"remembered: {fact}"}


@registry.tool(
    "Forget stored facts that match some text. Use when the user asks you to forget "
    "something about them.",
    {
        "type": "object",
        "properties": {
            "about": {
                "type": "string",
                "description": "Text to match against stored facts",
            }
        },
        "required": ["about"],
    },
)
def forget_fact(about: str) -> dict:
    if _memory is None:
        return {"ok": False, "error": "memory not available"}
    removed = _memory.remove_facts(about)
    if not removed:
        return {"ok": True, "message": f"nothing stored matched '{about}'"}
    return {
        "ok": True,
        "message": f"forgot {len(removed)} fact(s): " + "; ".join(removed),
        "removed": removed,
    }
