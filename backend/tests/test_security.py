"""Authorization is what stops a random website (or local process) from driving
Elara's tools. These pin the two-layer policy: token when present, else Origin."""

import pytest

from backend import security


@pytest.fixture(autouse=True)
def _clear_token(monkeypatch):
    monkeypatch.delenv("ELARA_TOKEN", raising=False)
    monkeypatch.delenv("ELARA_EXTRA_ORIGINS", raising=False)


def test_dev_mode_blocks_foreign_website():
    # No token configured: a page on evil.com sends its own Origin -> rejected.
    assert security.authorize("https://evil.com", None) is False


def test_dev_mode_allows_dev_server_origin():
    assert security.authorize("http://localhost:1420", None) is True


def test_dev_mode_allows_missing_origin_for_local_tools():
    assert security.authorize(None, None) is True


def test_token_mode_requires_matching_token(monkeypatch):
    monkeypatch.setenv("ELARA_TOKEN", "s3cret")
    # right token wins regardless of origin (webview can't be impersonated)
    assert security.authorize("https://evil.com", "s3cret") is True
    # wrong / missing token loses even from a trusted-looking origin
    assert security.authorize("http://localhost:1420", "nope") is False
    assert security.authorize("http://localhost:1420", None) is False


def test_extra_origins_env(monkeypatch):
    monkeypatch.setenv("ELARA_EXTRA_ORIGINS", "http://localhost:3000, https://x.test")
    assert "http://localhost:3000" in security.allowed_origins()
    assert security.authorize("https://x.test", None) is True
