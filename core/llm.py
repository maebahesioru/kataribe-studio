"""Kataribe Studio — LLM client.

OpenAI-compatible chat client with:
  - two named providers: "amd" (AMD Token Factory / AMD Instinct, primary)
    and "fallback" (local dev endpoint)
  - a usage meter (calls, tokens, latency per provider) that the UI exposes
  - JSON-mode helper with tolerant parsing (models sometimes wrap JSON in prose)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


PROVIDERS = ("amd", "fallback")


class TruncatedError(RuntimeError):
    """Model hit max_tokens before finishing its reply."""


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    label: str


def _cfg(name: str) -> ProviderConfig:
    prefix = "AMD" if name == "amd" else "FALLBACK"
    label = (
        "AMD Instinct — Token Factory (AMD Developer Cloud)"
        if name == "amd"
        else "Local dev endpoint"
    )
    return ProviderConfig(
        name=name,
        base_url=os.environ.get(f"{prefix}_BASE_URL", "").rstrip("/"),
        api_key=os.environ.get(f"{prefix}_API_KEY", ""),
        model=os.environ.get(f"{prefix}_MODEL", ""),
        label=label,
    )


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0
    errors: int = 0
    history: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "avg_latency_ms": round(self.total_ms / self.calls, 1) if self.calls else 0,
            "last_latency_ms": round(self.last_ms, 1),
            "errors": self.errors,
            "last_calls": self.history[-8:],
        }


class LLMClient:
    """Sync client (called from FastAPI's threadpool)."""

    def __init__(self, provider: str | None = None, timeout: float = 180.0):
        provider = provider or os.environ.get("LLM_PROVIDER", "fallback")
        if provider not in PROVIDERS:
            provider = "fallback"
        self.active = provider
        self.timeout = timeout
        self.usage: dict[str, Usage] = {p: Usage() for p in PROVIDERS}

    # ------------------------------------------------------------------ config
    def config(self) -> ProviderConfig:
        return _cfg(self.active)

    def set_provider(self, name: str) -> None:
        if name not in PROVIDERS:
            raise ValueError(f"unknown provider {name!r}")
        self.active = name

    def status(self) -> dict:
        out = {}
        for p in PROVIDERS:
            c = _cfg(p)
            u = self.usage[p]
            out[p] = {
                "label": c.label,
                "model": c.model,
                "base_url": c.base_url,
                "configured": bool(c.base_url and c.api_key),
                "usage": u.as_dict(),
            }
        out["active"] = self.active
        return out

    # -------------------------------------------------------------------- call
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.9,
        max_tokens: int = 1600,
        json_mode: bool = False,
    ) -> str:
        c = self.config()
        if not (c.base_url and c.api_key):
            raise RuntimeError(
                f"provider '{self.active}' is not configured "
                f"(set {'AMD' if self.active == 'amd' else 'FALLBACK'}_BASE_URL / _API_KEY)"
            )
        body: dict[str, Any] = {
            "model": c.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and os.environ.get("KATARIBE_JSON_MODE") == "1":
            # Some OpenAI-compatible gateways corrupt generations when
            # response_format=json_object is set; off unless explicitly enabled.
            body["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        u = self.usage[self.active]
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(
                    f"{c.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {c.api_key}"},
                    json=body,
                )
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            finish = choice.get("finish_reason")
            if not text.strip():
                # some providers only fill `reasoning` — treat empty content as error
                raise RuntimeError("empty completion content")
            if finish == "length":
                raise TruncatedError(
                    f"completion truncated at max_tokens={max_tokens}"
                )
            us = data.get("usage") or {}
            u.prompt_tokens += int(us.get("prompt_tokens") or 0)
            u.completion_tokens += int(us.get("completion_tokens") or 0)
            return text
        except Exception:
            u.errors += 1
            raise
        finally:
            dt = (time.monotonic() - started) * 1000.0
            u.calls += 1
            u.total_ms += dt
            u.last_ms = dt
            u.history.append(
                {"t": time.strftime("%H:%M:%S"), "ms": round(dt), "provider": self.active}
            )

    def chat_retry(self, system: str, user: str, *, max_tokens: int = 2000, **kw) -> str:
        """chat() with one automatic retry at 2x tokens when truncated."""
        try:
            return self.chat(system, user, max_tokens=max_tokens, **kw)
        except TruncatedError:
            return self.chat(system, user, max_tokens=min(max_tokens * 2, 8192), **kw)

    # ------------------------------------------------------------- json helper
    def chat_json(self, system: str, user: str, **kw) -> dict:
        """Chat expecting a JSON object back; tolerates prose-wrapped JSON."""
        kw.setdefault("max_tokens", 3000)
        raw = self.chat_retry(
            system + "\n\nReturn ONLY a single JSON object. No markdown fences, no commentary.",
            user,
            **kw,
        )
        return parse_json_object(raw)


def parse_json_object(raw: str) -> dict:
    """Extract the first JSON object from a model reply.

    Handles: pure JSON, ```json fenced blocks, prose + JSON, trailing text.
    """
    if not raw:
        raise ValueError("empty model reply")
    s = raw.strip()
    # strip code fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if m:
        s = m.group(1)
    # direct parse
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # scan for first balanced object
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break
        start = s.find("{", start + 1)
    raise ValueError(f"no JSON object found in reply: {raw[:200]!r}")
