"""Memory has to scale: surface relevant facts, forget precisely, summarise, and
not grow forever."""

import pytest

from backend.memory import Memory


@pytest.fixture
def mem(tmp_path):
    return Memory(tmp_path / "test.db")


def test_add_and_recall_messages(mem):
    mem.add_message("user", "hi")
    mem.add_message("assistant", "hello")
    msgs = mem.recent_messages(10)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hi"


def test_blank_messages_ignored(mem):
    mem.add_message("user", "   ")
    assert mem.message_count() == 0


def test_facts_all_returned_when_few(mem):
    mem.add_fact("Likes tea")
    mem.add_fact("Uses Vim")
    assert set(mem.relevant_facts("anything", 8)) == {"Likes tea", "Uses Vim"}


def test_relevant_facts_ranks_by_overlap(mem):
    for f in [
        "Has a dog named Pixel",
        "Prefers dark mode",
        "Works as a game developer",
        "Drinks black coffee",
        "Lives in Delhi",
        "Plays the guitar",
        "Favorite language is Rust",
        "Wife is called Anita",
        "On vacation next week",
    ]:
        mem.add_fact(f)
    top = mem.relevant_facts("tell me about my dog", 3)
    assert "Has a dog named Pixel" in top
    assert len(top) == 3


def test_remove_facts_is_word_precise(mem):
    mem.add_fact("On vacation next week")
    mem.add_fact("Has a cat named Milo")
    # 'cat' must not match 'vacation'
    removed = mem.remove_facts("cat")
    assert removed == ["Has a cat named Milo"]
    assert "On vacation next week" in mem.facts()


def test_remove_facts_returns_empty_when_no_match(mem):
    mem.add_fact("Likes tea")
    assert mem.remove_facts("coffee") == []


def test_summary_roundtrip(mem):
    assert mem.get_summary() == ""
    mem.set_summary("They set up the project today.")
    assert mem.get_summary() == "They set up the project today."


def test_prune_keeps_recent(mem):
    for i in range(20):
        mem.add_message("user", f"m{i}")
    removed = mem.prune_messages(5)
    assert removed == 15
    assert mem.message_count() == 5
    # the survivors are the most recent
    assert mem.recent_messages(5)[-1]["content"] == "m19"


def test_reset_clears_summary_and_messages(mem):
    mem.add_message("user", "hi")
    mem.set_summary("something")
    mem.clear_messages()
    mem.set_summary("")
    assert mem.message_count() == 0
    assert mem.get_summary() == ""
