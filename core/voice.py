"""Kataribe Studio — voice production (TTS).

Each character in the story bible gets a voice profile; this module maps those
profiles onto Japanese neural voices, applies per-character rate/pitch/volume,
and caches results so re-rendering an edited episode only synthesises what changed.

edge-tts is used as the local voice engine (free, offline-friendly cache, no API key).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

CACHE_DIR = Path(os.environ.get("KATARIBE_CACHE", "data/cache")).resolve()

# Voice pool — only voices verified to produce audio from this account/region.
# (ja-JP-Aoi/Mayu/Daichi/Naoki/Shiori currently return "no audio"; the
#  multilingual voices speak Japanese with distinct timbres instead.)
VOICE_POOL = {
    "female": [
        "ja-JP-NanamiNeural",            # native JP, bright standard
        "en-US-AvaMultilingualNeural",   # warm, expressive
        "en-US-EmmaMultilingualNeural",  # youthful
        "de-DE-SeraphinaMultilingualNeural",  # calm, mature
    ],
    "male": [
        "ja-JP-KeitaNeural",             # native JP, standard
        "en-US-AndrewMultilingualNeural",  # confident
        "en-US-BrianMultilingualNeural",   # soft-spoken
        "en-AU-WilliamMultilingualNeural",  # gentle, deep
    ],
}
# fallback chain if a voice ever stops producing audio
VOICE_FALLBACK = {"female": "ja-JP-NanamiNeural", "male": "ja-JP-KeitaNeural"}

NARRATOR_VOICE = "ja-JP-KeitaNeural"
NARRATOR_RATE = 0.92
NARRATOR_PITCH = -8


def voice_for(cast: list[dict], speaker_id: str) -> dict:
    """Resolve a speaker id → concrete synthesis parameters.

    Deterministic: the same cast always maps to the same voice.
    """
    if speaker_id in ("narration", "narrator", ""):
        return {
            "voice": NARRATOR_VOICE,
            "rate": NARRATOR_RATE,
            "pitch": NARRATOR_PITCH,
            "volume": 0,
        }
    for ch in cast:
        if ch.get("id") == speaker_id:
            v = ch.get("voice") or {}
            gender = v.get("gender", "female")
            pool = VOICE_POOL.get(gender) or VOICE_POOL["female"]
            # pick per-character slot by hashing the id → stable but varied
            idx = int(hashlib.sha1(speaker_id.encode()).hexdigest(), 16) % len(pool)
            rate = float(v.get("rate", 1.0))
            rate = min(max(rate, 0.8), 1.2)
            pitch = float(v.get("pitch", 0.0))
            pitch = min(max(pitch, -0.25), 0.25)
            return {
                "voice": pool[idx],
                "rate": round(rate, 2),
                "pitch": int(round(pitch * 100)) / 2,  # edge-tts wants Hz-ish steps
                "volume": 0,
            }
    # unknown speaker — narrator-ish default
    return {"voice": NARRATOR_VOICE, "rate": 1.0, "pitch": 0, "volume": 0}


def _cache_path(text: str, params: dict) -> Path:
    key = hashlib.sha1(
        json.dumps({"t": text, **params}, ensure_ascii=False).encode()
    ).hexdigest()
    return CACHE_DIR / f"{key}.mp3"


def synthesize(text: str, params: dict) -> tuple[Path, bool]:
    """Synthesise one line. Returns (path, from_cache)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(text, params)
    if path.exists() and path.stat().st_size > 0:
        return path, True
    rate = f"{'+' if params['rate'] >= 1 else '-'}{abs(params['rate'] - 1) * 100:.0f}%"
    pitch = f"{'+' if params['pitch'] >= 0 else '-'}{abs(params['pitch']):.0f}Hz"
    import edge_tts

    async def _run(voice: str):
        comm = edge_tts.Communicate(
            text,
            voice,
            rate=rate,
            pitch=pitch,
            volume="+0%",
        )
        await comm.save(str(path))

    import re as _re

    try:
        asyncio.run(_run(params["voice"]))
    except Exception as e:
        # voice died? fall back to the native-JP voice for this gender
        msg = str(e)
        if "No audio" in msg or "403" in msg or _re.search(r"handshake", msg, _re.I):
            gender = "male" if params["voice"] in VOICE_POOL["male"] else "female"
            fb = VOICE_FALLBACK[gender]
            if fb != params["voice"]:
                asyncio.run(_run(fb))
            else:
                raise
        else:
            raise
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"TTS produced no audio for {text[:30]!r}")
    return path, False


def synthesize_lines(script: dict, cast: list[dict], only_ids: list[str] | None = None):
    """Synthesise every line of a scene. Yields (line, path, cached) progress dicts."""
    only = set(only_ids) if only_ids else None
    for ln in script.get("lines", []):
        if only is not None and ln.get("id") not in only:
            continue
        params = voice_for(cast, ln.get("who", ""))
        path, cached = synthesize(ln.get("text", ""), params)
        yield {"id": ln.get("id"), "who": ln.get("who"), "voice": params["voice"],
                "path": str(path), "cached": cached}
