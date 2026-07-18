"""End-to-end exercise of the agent loop with a stand-in provider — no Ollama,
no network — covering the tricky bits: tool rounds, cross-round spacing, the
empty-promise nudge, and cooperative cancellation."""

import asyncio

import pytest

from backend.brain.agent import Agent
from backend.brain.provider import ChatChunk, ToolCall


class FakeTools:
    """Minimal stand-in for the tool registry."""

    def __init__(self, result=None):
        self.calls = []
        self._result = result or {"ok": True, "message": "did it"}

    def specs(self):
        return [{"type": "function", "function": {"name": "do_thing"}}]

    async def execute(self, name, args):
        self.calls.append((name, args))
        return self._result


class FakeProvider:
    """Yields a scripted sequence of turns. Each turn is a list of ChatChunks."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.on_iter = None  # optional hook called after each chunk
        self.seen_tools = []  # tool specs offered on each round

    async def chat_stream(self, messages, tools=None):
        self.seen_tools.append(tools)
        turn = self._turns.pop(0) if self._turns else []
        for chunk in turn:
            yield chunk
            if self.on_iter:
                self.on_iter()


class BoomProvider:
    """A cloud brain with no internet."""

    async def chat_stream(self, messages, tools=None):
        raise RuntimeError("no internet")
        yield  # pragma: no cover — makes this an async generator


async def _collect(agent, text):
    deltas, spoken = [], []

    async def emit(ev):
        if ev["type"] == "assistant_delta":
            deltas.append(ev["text"])

    async def on_sentence(sent, emotion):
        spoken.append(sent)

    reply = await agent.run_turn(text, emit, on_sentence)
    return reply, deltas, spoken


def test_plain_reply_no_tools():
    provider = FakeProvider([[ChatChunk(text="Hey there. All good?")]])
    agent = Agent(provider, FakeTools(), "Sir")
    reply, _deltas, spoken = asyncio.run(_collect(agent, "hi"))
    assert reply == "Hey there. All good?"
    assert spoken  # something was sent to TTS


def test_tool_round_then_answer_has_spacing():
    provider = FakeProvider(
        [
            [ChatChunk(text="Here's the plan."), ChatChunk(tool_calls=[
                ToolCall(id="1", name="do_thing", arguments={"x": 1})
            ])],
            [ChatChunk(text="It's sunny.")],
        ]
    )
    tools = FakeTools()
    agent = Agent(provider, tools, "Sir")
    reply, _deltas, _spoken = asyncio.run(_collect(agent, "weather?"))
    assert tools.calls == [("do_thing", {"x": 1})]
    # substantive rounds joined with a space, not glued into one word
    assert reply == "Here's the plan. It's sunny."


def test_filler_preamble_kept_out_of_transcript():
    # "Let me check" before a tool call is spoken once, live, but must not clutter
    # the final transcript — the answer round stands on its own.
    provider = FakeProvider(
        [
            [ChatChunk(text="Let me check."), ChatChunk(tool_calls=[
                ToolCall(id="1", name="do_thing", arguments={})
            ])],
            [ChatChunk(text="It's sunny.")],
        ]
    )
    agent = Agent(provider, FakeTools(), "Sir")
    reply, _deltas, spoken = asyncio.run(_collect(agent, "weather?"))
    assert reply == "It's sunny."  # preamble dropped from the transcript
    assert any("Let me check" in s for s in spoken)  # but it was voiced live


def test_yields_turn_after_asking_a_question():
    # She asks a question AND queues another tool call in the same round. The
    # loop must stop and wait for the user, not run the queued call.
    provider = FakeProvider(
        [
            [
                ChatChunk(text="Found a few headlines. Want me to dig deeper?"),
                ChatChunk(tool_calls=[ToolCall(id="2", name="do_thing", arguments={})]),
            ],
            [ChatChunk(text="This round should never run.")],
        ]
    )
    tools = FakeTools()
    agent = Agent(provider, tools, "Sir")
    reply, _deltas, _spoken = asyncio.run(_collect(agent, "ai news"))
    assert reply == "Found a few headlines. Want me to dig deeper?"
    assert tools.calls == []  # the queued tool call was dropped, not executed
    # nothing left dangling: no assistant message carrying unanswered tool_calls
    assert all(not m.get("tool_calls") for m in agent.history)


def test_turn_sentence_cap_stops_a_monologue():
    from backend.brain.agent import MAX_TURN_SENTENCES

    # a runaway reply streamed sentence by sentence, as Ollama would
    chunks = [ChatChunk(text=f"Sentence {i}. ") for i in range(12)]
    provider = FakeProvider([chunks])
    agent = Agent(provider, FakeTools(), "Sir")
    reply, _deltas, spoken = asyncio.run(_collect(agent, "ramble"))
    # capped to the turn budget, not the full twelve sentences
    assert len(spoken) == MAX_TURN_SENTENCES
    assert "Sentence 11." not in reply


def test_focus_mode_lifts_the_sentence_cap():
    # A focus task narrates progress across many steps; the chat cap must not
    # gag it. cloud_mode="always" runs uncapped from round one.
    long = [ChatChunk(text=f"Step {i} done. ") for i in range(8)]
    cloud = FakeProvider([long])
    agent = Agent(
        FakeProvider([]), FakeTools(), "Sir",
        cloud_provider=cloud, cloud_mode="always",
    )
    _reply, _deltas, spoken = asyncio.run(_collect(agent, "big task"))
    assert len(spoken) == 8  # all eight progress lines got through


def test_empty_promise_triggers_a_nudge_round():
    # First round promises with no tool call; the nudge should force another round.
    provider = FakeProvider(
        [
            [ChatChunk(text="Hold on, let me check that.")],
            [ChatChunk(text="It's 21 degrees.")],
        ]
    )
    agent = Agent(provider, FakeTools(), "Sir")
    reply, _deltas, _spoken = asyncio.run(_collect(agent, "temperature?"))
    assert "21 degrees" in reply
    # the transient nudge must not linger in history
    assert all(m.get("role") != "system" for m in agent.history)


def test_cancellation_stops_mid_stream():
    provider = FakeProvider(
        [[ChatChunk(text="Part one. "), ChatChunk(text="Part two.")]]
    )
    agent = Agent(provider, FakeTools(), "Sir")
    # simulate a new message cancelling this turn right after the first chunk
    provider.on_iter = agent.cancel
    reply, _deltas, _spoken = asyncio.run(_collect(agent, "go"))
    assert "Part one" in reply
    assert "Part two" not in reply


def test_reply_persisted_to_memory():
    class FakeMem:
        def __init__(self):
            self.msgs = []
            self.summary = ""

        def recent_messages(self, n):
            return []

        def add_message(self, role, content):
            self.msgs.append((role, content))

        def relevant_facts(self, q, n):
            return []

        def get_summary(self):
            return ""

    provider = FakeProvider([[ChatChunk(text="Done and done.")]])
    mem = FakeMem()
    agent = Agent(provider, FakeTools(), "Sir", mem)
    asyncio.run(_collect(agent, "do it"))
    assert ("user", "do it") in mem.msgs
    assert ("assistant", "Done and done.") in mem.msgs


def test_focus_mode_escalates_to_cloud():
    local = FakeProvider(
        [
            [
                ChatChunk(text="On it."),
                ChatChunk(
                    tool_calls=[
                        ToolCall(id="f1", name="enter_focus_mode", arguments={"task": "compare"})
                    ]
                ),
            ]
        ]
    )
    cloud = FakeProvider([[ChatChunk(text="Deep dive done.")]])
    tools = FakeTools()
    agent = Agent(local, tools, "Sir", cloud_provider=cloud, cloud_mode="auto")
    reply, _deltas, _spoken = asyncio.run(_collect(agent, "compare monitors"))
    assert "Deep dive done" in reply
    assert tools.calls == []  # enter_focus_mode is intercepted, never executed
    assert len(cloud.seen_tools) == 1  # cloud finished the turn


def test_focus_tool_offered_only_when_cloud_configured():
    with_cloud = FakeProvider([[ChatChunk(text="hi")]])
    agent = Agent(with_cloud, FakeTools(), "Sir",
                  cloud_provider=FakeProvider([]), cloud_mode="auto")
    asyncio.run(_collect(agent, "hello"))
    names = [t["function"]["name"] for t in with_cloud.seen_tools[0]]
    assert "enter_focus_mode" in names

    without = FakeProvider([[ChatChunk(text="hi")]])
    agent = Agent(without, FakeTools(), "Sir")
    asyncio.run(_collect(agent, "hello"))
    names = [t["function"]["name"] for t in without.seen_tools[0]]
    assert "enter_focus_mode" not in names


def test_cloud_mode_always_uses_cloud_from_round_one():
    local = FakeProvider([[ChatChunk(text="local")]])
    cloud = FakeProvider([[ChatChunk(text="cloud")]])
    agent = Agent(local, FakeTools(), "Sir", cloud_provider=cloud, cloud_mode="always")
    reply, _d, _s = asyncio.run(_collect(agent, "hi"))
    assert reply == "cloud"
    assert local.seen_tools == []  # local never consulted
    # cloud shouldn't be offered the escalation pseudo-tool
    names = [t["function"]["name"] for t in cloud.seen_tools[0]]
    assert "enter_focus_mode" not in names


def test_cloud_failure_falls_back_to_local():
    local = FakeProvider([[ChatChunk(text="Managed locally.")]])
    agent = Agent(local, FakeTools(), "Sir", cloud_provider=BoomProvider(), cloud_mode="always")
    reply, _d, _s = asyncio.run(_collect(agent, "hi"))
    assert reply == "Managed locally."
    # the cloud-down note was for this turn only
    assert all(m.get("role") != "system" for m in agent.history)


def test_tool_call_ids_threaded_into_history():
    provider = FakeProvider(
        [
            [ChatChunk(tool_calls=[ToolCall(id="abc", name="do_thing", arguments={})])],
            [ChatChunk(text="Done.")],
        ]
    )
    agent = Agent(provider, FakeTools(), "Sir")
    asyncio.run(_collect(agent, "go"))
    assistant = next(m for m in agent.history if m.get("tool_calls"))
    assert assistant["tool_calls"][0]["id"] == "abc"
    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "abc"


def test_huge_tool_result_is_truncated():
    from backend.brain.agent import MAX_TOOL_RESULT_CHARS

    provider = FakeProvider(
        [
            [ChatChunk(tool_calls=[ToolCall(id="1", name="do_thing", arguments={})])],
            [ChatChunk(text="Done.")],
        ]
    )
    tools = FakeTools(result={"ok": True, "message": "x" * 50_000})
    agent = Agent(provider, tools, "Sir")
    asyncio.run(_collect(agent, "go"))
    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert len(tool_msg["content"]) <= MAX_TOOL_RESULT_CHARS + 20
    assert tool_msg["content"].endswith("…[truncated]")
