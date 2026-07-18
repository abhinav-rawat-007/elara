"""The port-reuse decision is what stands between a fresh launch and a silent
mute: defer only to a backend the current UI can actually use, and take over a
stale one. These pin the classification down without opening a real socket."""

import json

import backend.main as main


class _Resp:
    """Minimal stand-in for urllib's response context manager."""

    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _fake_health(monkeypatch, token: str, payload: dict | None):
    monkeypatch.setattr(main.security, "expected_token", lambda: token)

    def urlopen(*_a, **_k):
        if payload is None:
            raise OSError("connection refused")
        return _Resp(payload)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def test_nothing_on_port_means_bind(monkeypatch):
    _fake_health(monkeypatch, "tokX", None)
    assert main._existing_instance() is None


def test_tokenless_dev_launch_defers_to_any_healthy(monkeypatch):
    # A manual `python main.py` (no token) should still bow out to a running one.
    _fake_health(monkeypatch, "", {"ok": True})
    assert main._existing_instance() == "compatible"


def test_matching_token_is_compatible(monkeypatch):
    _fake_health(monkeypatch, "tokX", {"ok": True, "authorized": True})
    assert main._existing_instance() == "compatible"


def test_mismatched_token_is_incompatible(monkeypatch):
    _fake_health(monkeypatch, "tokX", {"ok": True, "authorized": False})
    assert main._existing_instance() == "incompatible"


def test_old_backend_without_authorized_field_is_incompatible(monkeypatch):
    # A pre-fix instance never reports `authorized` — treat as a stale orphan
    # rather than deferring and muting the UI.
    _fake_health(monkeypatch, "tokX", {"ok": True})
    assert main._existing_instance() == "incompatible"
