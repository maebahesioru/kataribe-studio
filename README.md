# 🎙 Kataribe Studio

**An agentic production pipeline for serialized audio drama — story bible, script, direction,
voices and master, produced by agents running on AMD GPUs in the cloud.**

Kataribe Studio turns a one-line premise into a fully voiced Japanese audio-drama episode.
A *scriptwriter* agent develops the story bible and drafts scenes; a *director* agent
critiques them like a sharp editor; the human sits at the production desk — editing lines,
sending notes back — and the *voice booth* casts every character a distinct neural voice.
Everything the agents "think" runs on an OpenAI-compatible model endpoint hosted on
**AMD Instinct accelerators via the AMD Token Factory / AMD Developer Cloud**.

> Built for the **AMD Developer Hackathon ACT III** (track: *New Kind of Experience*).

---

## Why

Serialized audio drama is booming (podcasts, Spotify/audiobook platforms, web-novel
audio adaptations) — but producing even one episode traditionally means script writers,
voice actors, a studio and a mix engineer. Small creators and localization teams can't
afford that loop. Kataribe compresses *draft → critique → voices → master* into minutes,
and keeps the human where taste actually lives: **which lines survive, how they sound, what stays canon**.

- **Creators** ship episodes weekly instead of quarterly.
- **Publishers** prototype audio adaptation of a novel *before* paying for a full cast.
- **Every character voice is generated on demand** — recasts cost nothing.

## How it works

```
              ┌──────────────────────────── the studio server (FastAPI) ───────────────────────────┐
              │                                                                                    │
 premise ──▶  │  scripts desk        scriptwriter agent ─────┐                                     │
              │  (JSON, editable)    director agent  ────────┤──▶  OpenAI-compatible endpoint       │
              │                      continuity agent ───────┘     ┌──────────────────────────┐    │
              │                                                    │  AMD Token Factory /     │    │
              │  voice booth:    per-character neural TTS          │  AMD Developer Cloud     │    │
              │  mix stage:      ffmpeg loudness-normalized master  │  (AMD Instinct + ROCm)  │    │
              │                                                    └──────────────────────────┘    │
              │  UI shows live inference stats (calls · tokens · latency) per episode                │
              └────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Writers' room** — premise + genre + tone → the scriptwriter builds a story bible:
   original characters, speech styles, a series hook, and a **voice profile per character**.
2. **Episode plan** — a 3–4 scene outline with cold open, beats and a cliffhanger.
3. **Scene desk** — the scriptwriter drafts a scene as structured, performable JSON
   (`who / text / emotion / sfx`). You edit any line in place, delete, re-order, re-synth individually.
4. **Director review** — the director agent scores the scene, cites exact line ids,
   names the problem (flat exposition, repeated info, characters sounding alike) and gives
   a concrete fix; *apply direction* sends the notes back to the writer for a targeted rewrite.
5. **Voice booth** — every line is synthesized with its character's voice profile
   (voice, rate, pitch), cached by content hash — editing one line only re-renders one line.
6. **Master** — ffmpeg normalizes each line (EBU R128), joins them with dramatic pacing,
   lays a subtle room-tone bed and exports a broadcast-ready MP3 + the full transcript.
7. **Continuity** — the continuity agent writes the episode summary + open threads so
   episode N+1 starts consistent (a real serial, not isolated scenes).

## AMD: where the workload runs

Every LLM call in this application — bible, outline, scene, critique, rewrite, summary —
goes through **one OpenAI-compatible endpoint that runs on AMD infrastructure**:

```bash
# .env
AMD_BASE_URL=<your Token Factory endpoint>/v1   # from notebooks.amd.com/tokenfactory
AMD_API_KEY=<key>                               # never committed — environment only
AMD_MODEL=<open model from the catalogue>       # e.g. Qwen3
LLM_PROVIDER=amd
```

- The studio's **Inference · AMD** panel shows the active endpoint, model, and
  live usage (calls, tokens, average latency, errors) as the episode is produced —
  the judges can watch AMD inference happening in the product itself.
- Voice synthesis and mixing run locally (ffmpeg + neural TTS), so the AMD GPU
  cycles are spent on the part that matters: **language, judgement and creativity**.
- A `fallback` provider exists purely for local development; switch with one click
  (or `LLM_PROVIDER=fallback`) and the same pipeline runs against any local endpoint.

## Run it

Requires Python 3.10+, **ffmpeg** on PATH, and network access for the TTS engine.

```bash
git clone <this repo> && cd kataribe
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your AMD endpoint + key
python server.py            # → http://127.0.0.1:7866
```

Or with Docker:

```bash
docker build -t kataribe .
docker run --rm -p 7866:7866 --env-file .env -v kataribe-data:/data kataribe
```

Health check: `curl localhost:7866/api/status` → shows both providers and the live usage meter.

### Tests

```bash
pip install pytest
pytest -q
```

Covers JSON repair of messy model output, provider config, voice mapping, cache
behaviour, the audio proxy guard and the ffmpeg mix path (with generated tones).

## Project layout

```
server.py          FastAPI app — every endpoint is one production step
core/llm.py        OpenAI-compatible client + usage meter + truncation-aware retry
core/agents.py     the three agents: scriptwriter / director / continuity (prompts + schemas)
core/voice.py      per-character voice casting, synthesis, content-addressed cache
core/mixer.py      loudness-normalized, ambience-bedded episode master (ffmpeg)
core/store.py      series & episode persistence (plain JSON on disk)
static/            the studio UI (no framework, no build step)
scripts/           end-to-end pipeline smoke test
```

## The story format

Scenes are structured JSON — the contract that lets a *human* and three *agents* work on
the same artifact:

```json
{"id": "s1-l4", "who": "honoka", "text": "……先輩の声、聞こえた。", "emo": "囁き", "sfx": "真空管のノイズ"}
```

Line ids let the director cite exact lines, let rewrites be surgical, and let the voice
cache re-render only what changed.

## Roadmap

- [ ] Multi-voice engines (bring your own TTS provider per character)
- [ ] Sound-effect generation and BGM beds per scene
- [ ] Episode RSS feed + one-click publish to podcast hosts
- [ ] English/Chinese localization mode (same pipeline, target language)
- [ ] vLLM deployment templates for AMD Developer Cloud (self-hosted open models)

## License

MIT — see `LICENSE`. All characters and stories generated by the studio are original
creations; no third-party IP is included.
