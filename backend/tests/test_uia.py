"""UIA helpers that don't need a live desktop — key escaping and guards."""

from backend.tools.uia import _DESTRUCTIVE, _escape_keys


def test_escape_keys_makes_specials_literal():
    assert _escape_keys("a+b^c%d~e") == "a{+}b{^}c{%}d{~}e"
    assert _escape_keys("f(x) = {y}") == "f{(}x{)} = {{}y{}}"


def test_escape_keys_newline_becomes_enter():
    assert _escape_keys("line1\nline2") == "line1{ENTER}line2"


def test_destructive_control_names():
    assert _DESTRUCTIVE.search("Delete file")
    assert _DESTRUCTIVE.search("Uninstall")
    assert _DESTRUCTIVE.search("Reset settings")
    assert not _DESTRUCTIVE.search("Deleted items folder")  # word boundary
    assert not _DESTRUCTIVE.search("Play")
