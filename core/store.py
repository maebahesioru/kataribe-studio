"""Kataribe Studio — series & episode storage (plain JSON on disk)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("KATARIBE_DATA", "data")).resolve()
SERIES_DIR = DATA_DIR / "series"
EPISODES_DIR = DATA_DIR / "episodes"
AUDIO_DIR = DATA_DIR / "audio"


def _ensure():
    for d in (SERIES_DIR, EPISODES_DIR, AUDIO_DIR):
        d.mkdir(parents=True, exist_ok=True)


def new_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000):x}"


def save_json(path: Path, obj: dict) -> None:
    _ensure()
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- series


def save_series(series: dict) -> str:
    _ensure()
    series.setdefault("id", new_id("ser"))
    series["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_json(SERIES_DIR / f"{series['id']}.json", series)
    return series["id"]


def load_series(sid: str) -> dict:
    return load_json(SERIES_DIR / f"{sid}.json")


def list_series() -> list[dict]:
    _ensure()
    out = []
    for p in sorted(SERIES_DIR.glob("ser-*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            s = load_json(p)
            out.append({
                "id": s.get("id"),
                "title": (s.get("bible") or {}).get("title", "untitled"),
                "episodes": len(s.get("episodes", [])),
                "updated_at": s.get("updated_at"),
            })
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- episodes


def save_episode(series_id: str, episode: dict) -> Path:
    _ensure()
    ep = dict(episode)
    ep.setdefault("id", new_id("ep"))
    path = EPISODES_DIR / f"{series_id}__{ep['id']}.json"
    save_json(path, ep)
    return path


def load_episode(series_id: str, episode_id: str) -> dict:
    return load_json(EPISODES_DIR / f"{series_id}__{episode_id}.json")
