"""ClaudeCodeProvider's history→prompt mapping — pure, no SDK session."""

from backend.brain.claude_code import _short, to_prompt


def test_system_message_split_out():
    system, task = to_prompt(
        [
            {"role": "system", "content": "You are Elara."},
            {"role": "user", "content": "compare monitors for me"},
        ]
    )
    assert system == "You are Elara."
    assert "compare monitors for me" in task
    assert "You are Elara." not in task


def test_transcript_keeps_roles_and_skips_tool_noise():
    _, task = to_prompt(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "open steam"},
            {"role": "assistant", "content": "On it."},
            {"role": "tool", "tool_name": "open_app", "content": '{"ok": true}'},
            {"role": "system", "content": "nudge — call the tool"},
            {"role": "user", "content": "now launch the game"},
        ]
    )
    assert "User: open steam" in task
    assert "You (earlier): On it." in task
    assert "nudge" not in task
    assert '{"ok": true}' not in task
    assert task.strip().endswith("now launch the game")


def test_empty_history_still_yields_a_prompt():
    system, task = to_prompt([{"role": "system", "content": "sys"}])
    assert system == "sys"
    assert task  # never send an empty query


def test_mcp_prefix_stripped_for_ui_labels():
    assert _short("mcp__elara__open_app") == "open_app"
    assert _short("WebSearch") == "WebSearch"
