"""Tests for the ffmpeg mix path (generates tiny tones, no network)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import mixer  # noqa: E402


def _have_ffmpeg() -> bool:
    try:
        subprocess.run([mixer.FFMPEG, "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg not installed")


def _tone(path: Path, freq: int, dur: float = 0.7):
    subprocess.run([mixer.FFMPEG, "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={dur}",
                    "-ar", "24000", "-ac", "1", str(path)], capture_output=True, check=True)


def test_mix_two_line_episode(tmp_path):
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    _tone(a, 440), _tone(b, 660)
    scenes = [{"lines": [{"id": "l1", "path": str(a)}, {"id": "l2", "path": str(b)}]}]
    out = tmp_path / "ep.mp3"
    info = mixer.mix_episode(scenes, out, workdir=tmp_path / "work", ambience=True)
    assert info["lines"] == 2
    assert out.exists() and out.stat().st_size > 1000
    assert info["duration"] > 1.0  # two 0.7s lines + gap


def test_mix_skips_missing_files(tmp_path):
    a = tmp_path / "a.mp3"
    _tone(a, 440)
    scenes = [{"lines": [{"id": "l1", "path": str(a)},
                         {"id": "l2", "path": str(tmp_path / "missing.mp3")}]}]
    info = mixer.mix_episode(scenes, tmp_path / "ep.mp3", workdir=tmp_path / "w", ambience=False)
    assert info["lines"] == 1


def test_mix_empty_raises(tmp_path):
    try:
        mixer.mix_episode([{"lines": []}], tmp_path / "x.mp3", workdir=tmp_path / "w")
    except RuntimeError as e:
        assert "nothing to mix" in str(e)
        return
    raise AssertionError("expected RuntimeError")


def test_probe_duration(tmp_path):
    a = tmp_path / "t.mp3"
    _tone(a, 440, 1.2)
    assert abs(mixer.probe_duration(a) - 1.2) < 0.2
