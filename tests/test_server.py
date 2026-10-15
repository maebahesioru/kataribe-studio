"""API-level tests: status, audio proxy guard, episode snapshot roundtrip."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KATARIBE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("KATARIBE_CACHE", str(tmp_path / "cache"))
    # drop cached modules so path constants recompute under the temp env
    for mod in ["core.store", "core.voice", "server"]:
        sys.modules.pop(mod, None)
    import server  # noqa
    return TestClient(server.app)


def test_status_shape(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"amd", "fallback", "active", "voices"}


def test_audio_proxy_blocks_outside_cache(client, tmp_path):
    victim = tmp_path / "secret.txt"
    victim.write_text("nope")
    r = client.get("/api/audio_proxy", params={"path": str(victim)})
    assert r.status_code in (403, 404)


def test_audio_proxy_serves_cached_file(client, tmp_path, monkeypatch):
    import server
    cache = server.voice.CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / "x.mp3"
    f.write_bytes(b"ID3fake")
    r = client.get("/api/audio_proxy", params={"path": str(f)})
    assert r.status_code == 200 and r.content == b"ID3fake"


def test_episode_save_and_demo_last(client):
    payload = {
        "bible": {"title": "t", "cast": []},
        "outline": {"scenes": [{"no": 1, "title": "s"}]},
        "episode_no": 1,
        "episode_title": "pilot",
        "scene": {"lines": [{"id": "l1", "who": "narration", "text": "x"}]},
        "audio": {},
        "mp3": "",
    }
    r = client.post("/api/episode/save", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/demo/last")
    assert r2.status_code == 200
    assert r2.json()["episode_title"] == "pilot"
    assert r2.json()["scene"]["lines"][0]["id"] == "l1"


def test_provider_switch(client):
    r = client.post("/api/provider", json={"provider": "amd"})
    assert r.status_code == 200
    assert r.json()["active"] == "amd"
    r = client.post("/api/provider", json={"provider": "bogus"})
    assert r.status_code == 400
    client.post("/api/provider", json={"provider": "fallback"})
