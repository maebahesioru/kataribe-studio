"""Kataribe Studio — FastAPI server.

Endpoints
  GET  /                    studio UI
  GET  /api/status          providers + usage meter (the AMD panel reads this)
  POST /api/provider        switch provider {"provider": "amd"|"fallback"}
  POST /api/bible           premise → story bible (cast, voices)
  POST /api/outline         bible → episode outline
  POST /api/scene           outline scene → dialogue script
  POST /api/direct          scene → director review (critique + issues)
  POST /api/rewrite         lines + director notes → rewritten lines
  POST /api/voice           scene + cast → synthesised per-line audio
  POST /api/render          episode audio → mp3 mixdown
  GET  /api/series          list saved series
  POST /api/series/save     persist a series (episodes + continuity)
  GET  /api/episodes/{sid}  load a series
  GET  /audio/...           static audio files (episode mp3s)
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")

from core import agents as agents_mod  # noqa: E402
from core import mixer, store, voice  # noqa: E402
from core.llm import LLMClient  # noqa: E402

app = FastAPI(title="Kataribe Studio")
llm = LLMClient()
agents = agents_mod.Agents(llm)

STATIC = Path(__file__).parent / "static"
AUDIO = Path(os.environ.get("KATARIBE_DATA", "data")).resolve() / "audio"
AUDIO.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def no_cache_shell(request, call_next):
    """The studio shell must never be served stale during iteration/demos."""
    resp = await call_next(request)
    if request.url.path in ("/", "/index.html", "/app.js", "/style.css"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ models


class BibleReq(BaseModel):
    premise: str
    genre: str = "ミステリー"
    tone: str = "温かいが少し不穏"
    cast_size: int = 3


class OutlineReq(BaseModel):
    bible: dict
    prev_summary: str = ""
    episode_no: int = 1


class SceneReq(BaseModel):
    bible: dict
    episode_no: int = 1
    episode_title: str = ""
    scene: dict


class DirectReq(BaseModel):
    bible: dict
    scene: dict
    notes: str = ""


class RewriteReq(BaseModel):
    bible: dict
    lines: list
    notes: str


class VoiceReq(BaseModel):
    scene: dict
    cast: list
    only_ids: list[str] | None = None


class RenderReq(BaseModel):
    scenes: list
    out_name: str = "episode"


class ProviderReq(BaseModel):
    provider: str


class SeriesReq(BaseModel):
    series: dict


# ------------------------------------------------------------------ routes


@app.get("/api/status")
def status():
    st = llm.status()
    st["voices"] = {g: v for g, v in voice.VOICE_POOL.items()}
    st["narrator"] = voice.NARRATOR_VOICE
    return st


@app.post("/api/provider")
def set_provider(req: ProviderReq):
    try:
        llm.set_provider(req.provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return llm.status()


@app.post("/api/bible")
def make_bible(req: BibleReq):
    try:
        return agents.bible(req.premise, req.genre, req.tone, req.cast_size)
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/outline")
def make_outline(req: OutlineReq):
    try:
        return agents.outline(req.bible, req.prev_summary, req.episode_no)
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/scene")
def make_scene(req: SceneReq):
    try:
        return agents.scene(req.bible, req.episode_no, req.episode_title, req.scene)
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/direct")
def direct(req: DirectReq):
    try:
        return agents.direct(req.bible, req.scene, req.notes)
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/rewrite")
def rewrite(req: RewriteReq):
    try:
        return {"lines": agents.rewrite(req.bible, req.lines, req.notes)}
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/voices_for")
def voices_for(req: VoiceReq):
    """Resolve the cast to concrete voice parameters (shown in the UI)."""
    return {
        "voices": [
            {"id": ch.get("id"), "name": ch.get("name"), **voice.voice_for(req.cast, ch.get("id"))}
            for ch in req.cast
        ]
    }


class SummaryReq(BaseModel):
    episode_no: int
    episode_title: str
    scene_texts: list[str]


@app.post("/api/summary")
def summary(req: SummaryReq):
    try:
        return agents.summarise(req.episode_no, req.episode_title, req.scene_texts)
    except Exception as e:
        raise HTTPException(502, f"model error: {e}")


@app.post("/api/voice")
def make_voice(req: VoiceReq):
    try:
        out = list(voice.synthesize_lines(req.scene, req.cast, req.only_ids))
        for o in out:
            o["url"] = "/api/audio_proxy?path=" + quote(o["path"])
        return {"lines": out, "synthesized": sum(1 for o in out if not o["cached"])}
    except Exception as e:
        raise HTTPException(502, f"voice error: {e}")


@app.get("/api/audio_proxy")
def audio_proxy(path: str):
    """Serve synthesised line audio (only from the voice cache directory)."""
    p = Path(path).resolve()
    cache_root = voice.CACHE_DIR.resolve()
    try:
        p.relative_to(cache_root)
    except ValueError:
        raise HTTPException(403, "path outside cache")
    if not p.exists():
        raise HTTPException(404, "no such audio")
    return FileResponse(str(p), media_type="audio/mpeg")


@app.post("/api/render")
def render(req: RenderReq):
    try:
        safe = "".join(c for c in req.out_name if c.isalnum() or c in "-_") or "episode"
        out = AUDIO / f"{safe}.mp3"
        info = mixer.mix_episode(req.scenes, out, ambience=True)
        info["url"] = f"/audio/{out.name}"
        return info
    except Exception as e:
        raise HTTPException(502, f"render error: {e}")


@app.get("/api/series")
def series_list():
    return {"series": store.list_series()}


@app.post("/api/series/save")
def series_save(req: SeriesReq):
    sid = store.save_series(req.series)
    return {"id": sid}


class EpisodeSaveReq(BaseModel):
    bible: dict
    outline: dict
    episode_no: int
    episode_title: str
    scene: dict
    audio: dict          # line id -> filesystem path
    mp3: str = ""


@app.post("/api/episode/save")
def episode_save(req: EpisodeSaveReq):
    """Snapshot the working scene so a session can be resumed exactly."""
    ep = {
        "bible": req.bible,
        "outline": req.outline,
        "episode_no": req.episode_no,
        "episode_title": req.episode_title,
        "scene": req.scene,
        "audio": req.audio,
        "mp3": req.mp3,
    }
    sid = store.save_series({"bible": req.bible, "outline": req.outline,
                             "history": [], "episodes": [{"no": req.episode_no, "title": req.episode_title}]})
    path = store.save_episode(sid, ep)
    return {"series_id": sid, "episode_path": str(path)}


@app.get("/api/demo/last")
def demo_last():
    """Most recent episode snapshot, with audio resolved to playable URLs."""
    eps = sorted(store.EPISODES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not eps:
        raise HTTPException(404, "no saved episode")
    ep = store.load_json(eps[0])
    audio = {}
    for lid, p in (ep.get("audio") or {}).items():
        pp = Path(p)
        if pp.exists():
            audio[lid] = {"path": p, "url": "/api/audio_proxy?path=" + quote(p)}
    ep["audio_resolved"] = audio
    if ep.get("mp3"):
        name = Path(ep["mp3"]).name
        if (AUDIO / name).exists():
            ep["mp3_url"] = "/audio/" + name
    return ep


@app.get("/api/episodes/{sid}")
def episodes_get(sid: str):
    try:
        return store.load_series(sid)
    except FileNotFoundError:
        raise HTTPException(404, "series not found")


# ------------------------------------------------------------------ static

app.mount("/audio", StaticFiles(directory=str(AUDIO)), name="audio")
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7866)))
