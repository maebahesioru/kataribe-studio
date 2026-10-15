#!/usr/bin/env python3
"""End-to-end pipeline smoke test against a running Kataribe server.

Usage: .venv/bin/python scripts/pipeline_test.py
Exercises: bible → outline → scene → direct → rewrite → voice → render → save.
Prints a stage-by-stage report. Safe to re-run (voice cache makes it fast).
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7866"


def call(path, body=None, timeout=300):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data, time.time() - t0


def main():
    premise = ("海辺の町の高校、放課後の放送部。古い受信機が、"
               "死んだはずの先輩の声を受信しはじめる。")
    st, dt = call("/api/status")
    print(f"[status] active={st['active']} model={st[st['active']]['model']} ({dt:.1f}s)")

    bible, dt = call("/api/bible", {"premise": premise, "genre": "ミステリー",
                                    "tone": "温かいが少し不穏", "cast_size": 3})
    print(f"[bible] 「{bible.get('title')}」 cast={len(bible.get('cast', []))} ({dt:.1f}s)")

    outline, dt = call("/api/outline", {"bible": bible, "episode_no": 1})
    print(f"[outline] ep1「{outline.get('episode_title')}」 scenes={len(outline.get('scenes', []))} ({dt:.1f}s)")

    scene_meta = outline["scenes"][0]
    scene, dt = call("/api/scene", {"bible": bible, "episode_no": 1,
                                    "episode_title": outline.get("episode_title", ""),
                                    "scene": scene_meta})
    lines = scene.get("lines", [])
    print(f"[scene] S{scene_meta['no']}「{scene.get('scene_title')}」 lines={len(lines)} ({dt:.1f}s)")
    for ln in lines[:4]:
        print(f"   {ln['id']:8s} {ln['who']:9s} {ln['text'][:42]}")

    review, dt = call("/api/direct", {"bible": bible, "scene": scene, "notes": ""})
    print(f"[director] score={review.get('score')} issues={len(review.get('issues', []))} ({dt:.1f}s)")
    for iss in review.get("issues", [])[:2]:
        print(f"   - {iss.get('line_id')}: {iss.get('issue', '')[:60]}")

    if review.get("issues"):
        ids = [i["line_id"] for i in review["issues"]]
        flagged = [l for l in lines if l["id"] in ids]
        notes = "\n".join(f"line {i['line_id']}: {i['issue']} → {i['fix']}"
                          for i in review["issues"])
        rew, dt = call("/api/rewrite", {"bible": bible, "lines": flagged, "notes": notes})
        print(f"[rewrite] {len(rew.get('lines', []))} lines revised ({dt:.1f}s)")
        for rl in rew.get("lines", []):
            cur = next((l for l in lines if l["id"] == rl["id"]), None)
            if cur:
                cur.update(rl)

    voices, dt = call("/api/voice", {"scene": scene, "cast": bible.get("cast", [])})
    print(f"[voice] {len(voices['lines'])} lines ({voices['synthesized']} new) ({dt:.1f}s)")

    scenes = [{"lines": [{"id": v["id"], "path": v["path"]} for v in voices["lines"]]}]
    info, dt = call("/api/render", {"scenes": scenes, "out_name": "pipeline-test"})
    print(f"[render] {info['duration']}s -> {info['url']} ({dt:.1f}s)")

    series = {"bible": bible, "outline": outline, "history": [],
              "episodes": [{"no": s["no"], "title": s["title"]} for s in outline["scenes"]]}
    saved, _ = call("/api/series/save", {"series": series})
    print(f"[save] series {saved.get('id')}")
    print("PIPELINE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("PIPELINE FAIL:", e)
        sys.exit(1)
