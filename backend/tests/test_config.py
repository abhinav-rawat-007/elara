"""set_config accepts values straight off the wire, so apply_patch must coerce
or reject bad types rather than let them poison a field."""

from backend.config import Config, _coerce


def test_valid_patch_applies():
    c = Config()
    c.apply_patch({"speak_replies": False, "user_name": "Sir", "proactive_minutes": 20})
    assert c.speak_replies is False
    assert c.user_name == "Sir"
    assert c.proactive_minutes == 20


def test_wrong_types_are_rejected_not_crashing():
    c = Config()
    c.apply_patch({"proactive_minutes": "abc", "user_name": 123})
    # bad values ignored, fields keep their prior valid values
    assert isinstance(c.proactive_minutes, int)
    assert c.user_name == "friend"


def test_string_bools_coerced():
    c = Config()
    c.apply_patch({"speak_replies": "off", "proactive": "true"})
    assert c.speak_replies is False
    assert c.proactive is True


def test_proactive_minutes_clamped():
    c = Config()
    c.apply_patch({"proactive_minutes": 9999})
    assert c.proactive_minutes == 240
    c.apply_patch({"proactive_minutes": 0})
    assert c.proactive_minutes == 1


def test_unknown_keys_ignored():
    c = Config()
    c.apply_patch({"nonexistent": "x", "model": "qwen3:8b"})
    assert not hasattr(c, "nonexistent")
    assert c.model == "qwen3:8b"


def test_coerce_bool_rejects_non_bool_for_int_field():
    # bool is an int subclass — must not sneak into an int field
    assert _coerce("int", True) is None


def test_coerce_str_rejects_numbers():
    assert _coerce("str", 5) is None
    assert _coerce("str", "ok") == "ok"
