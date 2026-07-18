"""The Anthropic message/tool mapping — pure functions, no network, no SDK calls.

The agent loop keeps history in Ollama's shape; AnthropicProvider maps at the
edge. These tests pin the tricky parts: system extraction, the mid-history
nudge, tool_use/tool_result id threading, and same-role merging.
"""

from backend.brain.provider import _to_anthropic_messages, _to_anthropic_tools


def test_leading_system_becomes_param():
    system, out = _to_anthropic_messages(
        [
            {"role": "system", "content": "You are Elara."},
            {"role": "user", "content": "hi"},
        ]
    )
    assert system == "You are Elara."
    assert out == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_mid_history_system_note_becomes_user_turn():
    system, out = _to_anthropic_messages(
        [
            {"role": "system", "content": "You are Elara."},
            {"role": "user", "content": "check it"},
            {"role": "assistant", "content": "One sec."},
            {"role": "system", "content": "call the tool NOW"},
        ]
    )
    assert system == "You are Elara."
    last = out[-1]
    assert last["role"] == "user"
    assert "<system-note>call the tool NOW</system-note>" in last["content"][0]["text"]


def test_tool_calls_map_to_tool_use_and_results_merge():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "compare"},
        {
            "role": "assistant",
            "content": "ok",
            "tool_calls": [
                {"id": "a1", "function": {"name": "t1", "arguments": {"x": 1}}},
                # OpenAI-style providers stream arguments as a JSON string
                {"id": "a2", "function": {"name": "t2", "arguments": '{"y": 2}'}},
            ],
        },
        {"role": "tool", "tool_name": "t1", "tool_call_id": "a1", "content": "r1"},
        {"role": "tool", "tool_name": "t2", "tool_call_id": "a2", "content": "r2"},
    ]
    system, out = _to_anthropic_messages(messages)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]

    tool_uses = [b for b in out[1]["content"] if b["type"] == "tool_use"]
    assert [(t["id"], t["name"]) for t in tool_uses] == [("a1", "t1"), ("a2", "t2")]
    assert tool_uses[0]["input"] == {"x": 1}
    assert tool_uses[1]["input"] == {"y": 2}

    # consecutive tool messages fold into ONE user turn with two tool_results
    results = [b for b in out[2]["content"] if b["type"] == "tool_result"]
    assert [r["tool_use_id"] for r in results] == ["a1", "a2"]
    assert [r["content"] for r in results] == ["r1", "r2"]


def test_assistant_with_empty_text_keeps_only_tool_use():
    _, out = _to_anthropic_messages(
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "a1", "function": {"name": "t", "arguments": {}}}],
            },
        ]
    )
    blocks = out[1]["content"]
    assert all(b["type"] == "tool_use" for b in blocks)


def test_history_opening_with_assistant_gets_user_opener():
    # restored history can start with one of her proactive lines
    _, out = _to_anthropic_messages([{"role": "assistant", "content": "Still there?"}])
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"


def test_tools_spec_mapping():
    specs = [
        {
            "type": "function",
            "function": {
                "name": "open_app",
                "description": "Open an app.",
                "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        }
    ]
    mapped = _to_anthropic_tools(specs)
    assert mapped == [
        {
            "name": "open_app",
            "description": "Open an app.",
            "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
    ]
