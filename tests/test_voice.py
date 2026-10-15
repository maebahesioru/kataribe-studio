"""Tests for voice casting + cache addressing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import voice  # noqa: E402

CAST = [
    {"id": "aoi", "name": "碧", "voice": {"gender": "female", "rate": 1.05, "pitch": 0.1}},
    {"id": "ren", "name": "蓮", "voice": {"gender": "male", "rate": 0.92, "pitch": -0.15}},
]


def test_narration_params():
    p = voice.voice_for(CAST, "narration")
    assert p["voice"] == voice.NARRATOR_VOICE
    assert p["rate"] < 1.0


def test_cast_params_stable_and_clamped():
    a = voice.voice_for(CAST, "aoi")
    b = voice.voice_for(CAST, "aoi")
    assert a == b  # deterministic
    assert a["voice"] in voice.VOICE_POOL["female"]
    assert 0.8 <= a["rate"] <= 1.2
    assert -25 <= a["pitch"] <= 25
    r = voice.voice_for(CAST, "ren")
    assert r["voice"] in voice.VOICE_POOL["male"]


def test_unknown_speaker_falls_back_to_narrator_like():
    p = voice.voice_for(CAST, "ghost")
    assert p["voice"] == voice.NARRATOR_VOICE


def test_cache_path_is_content_addressed():
    p1 = voice._cache_path("同じ台詞", {"voice": "v", "rate": 1.0, "pitch": 0, "volume": 0})
    p2 = voice._cache_path("同じ台詞", {"voice": "v", "rate": 1.0, "pitch": 0, "volume": 0})
    p3 = voice._cache_path("違う台詞", {"voice": "v", "rate": 1.0, "pitch": 0, "volume": 0})
    assert p1 == p2 and p1 != p3
    assert p1.suffix == ".mp3"


def test_voice_pool_limited_to_verified_voices():
    # region-restricted voices must not be back in the pool
    banned = {"ja-JP-AoiNeural", "ja-JP-MayuNeural", "ja-JP-DaichiNeural",
              "ja-JP-NaokiNeural", "ja-JP-ShioriNeural"}
    for pool in voice.VOICE_POOL.values():
        assert not (set(pool) & banned)
