"""Kataribe Studio — episode mixdown.

Takes the synthesised per-line audio and produces a broadcast-ready episode:
  1. per-line loudness normalisation (EBU R128, so quiet whispers don't vanish)
  2. gaps between lines (short for dialogue turns, longer at scene cuts)
  3. a soft ambience bed under the whole episode (optional)
  4. master loudness normalisation + mp3 export

ffmpeg (system binary) does the heavy lifting.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

GAP_LINE = 0.35      # seconds between lines inside a scene
GAP_SCENE = 1.4      # seconds between scenes
TARGET_LUFS = -16.0  # streaming drama loudness


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def probe_duration(path: str | Path) -> float:
    r = _run([FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {r.stderr[:200]}")
    data = json.loads(r.stdout)
    return float(data["format"]["duration"])


def _silence(seconds: float, out: Path) -> Path:
    _run([FFMPEG, "-y", "-f", "lavfi", "-i",
          f"anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}", "-q:a", "9", str(out)])
    return out


def _normalize_line(src: Path, out: Path) -> Path:
    _run([FFMPEG, "-y", "-i", str(src), "-af",
          f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=9",
          "-ar", "24000", "-ac", "1", str(out)])
    return out


def mix_episode(
    scenes: list[dict],
    out_path: str | Path,
    workdir: str | Path | None = None,
    ambience: bool = True,
) -> dict:
    """Mix an episode.

    scenes: [{"lines": [{"id":..., "path": <mp3/ogg path>, ...}, ...]}, ...]
    Returns {"out": path, "duration": sec, "lines": n}
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="kataribe_mix_"))
    tmp.mkdir(parents=True, exist_ok=True)

    parts: list[Path] = []
    n_lines = 0
    for si, scene in enumerate(scenes):
        for li, ln in enumerate(scene.get("lines", [])):
            p = Path(ln["path"])
            if not p.exists():
                continue
            norm = _normalize_line(p, tmp / f"n_{si}_{li}.wav")
            parts.append(norm)
            n_lines += 1
            gap = GAP_SCENE if li == len(scene.get("lines", [])) - 1 else GAP_LINE
            # short tail for the last line of the last scene
            parts.append(_silence(gap, tmp / f"g_{si}_{li}.wav"))

    if not parts:
        raise RuntimeError("nothing to mix — no synthesised lines found")

    # concat list
    lst = tmp / "concat.txt"
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    body = tmp / "body.wav"
    r = _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
              "-ar", "24000", "-ac", "1", str(body)])
    if r.returncode != 0:
        raise RuntimeError(f"concat failed: {r.stderr[-300:]}")

    if ambience:
        # soft room tone: low-passed pink noise, very quiet — glue between lines
        amb = tmp / "amb.wav"
        dur = probe_duration(body)
        _run([FFMPEG, "-y", "-f", "lavfi", "-i",
              f"anoisesrc=color=pink:amplitude=0.010:duration={dur:.2f}",
              "-af", "lowpass=f=900", "-ar", "24000", "-ac", "1", str(amb)])
        mixed = tmp / "mixed.wav"
        _run([FFMPEG, "-y", "-i", str(body), "-i", str(amb),
              "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0",
              "-ar", "24000", "-ac", "1", str(mixed)])
        master_in = mixed
    else:
        master_in = body

    r = _run([FFMPEG, "-y", "-i", str(master_in), "-af",
              f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11",
              "-ar", "44100", "-ac", "2", "-b:a", "192k", str(out_path)])
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"master failed: {r.stderr[-300:]}")

    return {"out": str(out_path), "duration": round(probe_duration(out_path), 1), "lines": n_lines}
