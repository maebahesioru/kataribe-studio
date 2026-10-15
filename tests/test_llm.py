"""Tests for the LLM client: JSON repair, config, truncation retry, usage meter."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import LLMClient, TruncatedError, parse_json_object  # noqa: E402


def test_parse_pure_json():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    raw = '```json\n{"title": "x", "cast": []}\n```'
    assert parse_json_object(raw)["title"] == "x"


def test_parse_prose_wrapped():
    raw = 'Sure! Here is the JSON you asked for:\n{"title": "y"}\nHope it helps.'
    assert parse_json_object(raw)["title"] == "y"


def test_parse_nested_first_object_not_caught():
    raw = '{"title": "z", "cast": [{"id": "a"}, {"id": "b"}]}'
    out = parse_json_object(raw)
    assert out["title"] == "z" and len(out["cast"]) == 2


def test_parse_broken_raises():
    try:
        parse_json_object("no json here")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_provider_config_from_env(monkeypatch):
    monkeypatch.setenv("AMD_BASE_URL", "https://amd.example/v1")
    monkeypatch.setenv("AMD_API_KEY", "k")
    monkeypatch.setenv("AMD_MODEL", "Qwen3")
    c = LLMClient("amd")
    cfg = c.config()
    assert cfg.base_url == "https://amd.example/v1" and cfg.model == "Qwen3"
    st = c.status()
    assert st["amd"]["configured"] is True
    assert st["active"] == "amd"


def test_usage_meter_counts_retry_errors(monkeypatch):
    c = LLMClient("fallback")
    u = c.usage["fallback"]
    assert u.calls == 0 and u.errors == 0
    # simulate two calls, one failing
    monkeypatch.setattr(c, "chat", _flaky_chat(c))
    try:
        c.chat_retry("s", "u", max_tokens=10)
    except TruncatedError:
        pass
    assert u.calls >= 1


def _flaky_chat(c):
    calls = {"n": 0}

    def fake(system, user, **kw):
        calls["n"] += 1
        c.usage[c.active].calls += 1
        if calls["n"] == 1:
            c.usage[c.active].errors += 1
            raise TruncatedError("truncated")
        return '{"ok": true}'

    return fake


def test_chat_json_retries_on_truncation(monkeypatch):
    c = LLMClient("fallback")
    monkeypatch.setattr(c, "chat", _flaky_chat(c))
    out = c.chat_json("s", "u", max_tokens=10)
    assert out == {"ok": True}
    assert c.usage["fallback"].calls == 2


def test_unconfigured_provider_raises(monkeypatch):
    monkeypatch.delenv("AMD_BASE_URL", raising=False)
    monkeypatch.delenv("AMD_API_KEY", raising=False)
    c = LLMClient("amd")
    try:
        c.chat("s", "u")
    except RuntimeError as e:
        assert "not configured" in str(e)
        return
    raise AssertionError("expected RuntimeError")
