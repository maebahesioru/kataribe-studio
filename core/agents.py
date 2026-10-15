"""Kataribe Studio — agent prompts and script operations.

Three roles on one model (as in a real audio-drama production):
  1. Scriptwriter  — story bible, scene scripts in structured JSON
  2. Director      — critiques pacing/characterisation, rewrites weak lines
  3. Continuity    — episode summaries so the serial stays consistent

The model never sees free-form requests from the browser: every call goes
through these typed builders, which keeps outputs parseable and auditable.
"""
from __future__ import annotations

from .llm import LLMClient

# ---------------------------------------------------------------------------
# Scriptwriter — story bible
# ---------------------------------------------------------------------------

BIBLE_SYSTEM = """You are the lead scriptwriter of a professional Japanese audio-drama
(音声ドラマ) studio. You write serialized audio fiction for streaming — every word
will be performed by voice actors, so your writing must sound natural aloud.

You create compact, vivid, original stories. No existing IP, no real people.
Write all in-world content (names, places, lines) in Japanese; JSON keys in English.

Character voices must be distinct enough that a listener recognises who speaks
without a name tag: give each character a speaking style (口癖, tempo, vocabulary)."""

BIBLE_USER = """Create a story bible for a serialized audio drama.

Premise: {premise}
Genre: {genre}
Tone: {tone}
Number of characters: {cast_size}

Return a JSON object:
{{
 "title": "Japanese title",
 "logline": "one sentence, Japanese",
 "world": "2-3 sentences on the setting and the central mystery/conflict, Japanese",
 "cast": [
   {{"id": "short_ascii_id", "name": "Japanese name", "role": "役割 (short)",
     "personality": "2 sentences, Japanese",
     "speech_style": "how they talk — 口癖, tempo (Japanese)",
     "voice": {{"gender": "female|male", "style": "e.g. 明るい少女 / 落ち着いた青年",
               "rate": 1.0, "pitch": 0.0}}}}
 ],
 "series_hook": "the question that makes listeners come back next episode (Japanese)"
}}

Use rate 0.85-1.15 and pitch -0.2..0.2 to differentiate voices.
Every character must be an original creation."""

# ---------------------------------------------------------------------------
# Scriptwriter — episode outline + scenes
# ---------------------------------------------------------------------------

OUTLINE_SYSTEM = """You are the scriptwriter of a serialized Japanese audio drama.
You plan episodes that end on a hook. Audio-only: no visual gags, no camera directions.
Drama is carried by dialogue, sound effects and narration (ナレーション)."""

OUTLINE_USER = """Story bible:
{bible_json}

Previous episodes summary:
{prev_summary}

Plan episode {episode_no}. Return JSON:
{{
 "episode_title": "Japanese",
 "cold_open": "one-line teaser (Japanese)",
 "scenes": [
   {{"no": 1, "title": "Japanese", "setting": "where/when (Japanese)",
     "beats": "2-3 sentences: what happens, who wants what (Japanese)",
     "ends_with": "the beat that hands off to the next scene"}}
 ],
 "cliffhanger": "the final hook (Japanese)"
}}
3-4 scenes, each 6-12 lines of dialogue when scripted."""

SCENE_SYSTEM = """You are the scriptwriter of a serialized Japanese audio drama.
You write one scene in a structured, performable format.

Rules:
- Dialogue must sound like real speech (自然な口語). No stage directions inside lines.
- Narration (who="narration") only for time/place shifts and inner thoughts — 1-2 lines per scene.
- Put sound effects in the "sfx" field, not in dialogue text.
- "emo" guides the voice actor: one short Japanese word (e.g. 明るく/囁き/焦り/静かに).
- Keep each line under 90 Japanese characters so it performs well.
- Character ids must come from the bible's cast ids."""

SCENE_USER = """Story bible:
{bible_json}

Episode {episode_no}: {episode_title}
Scene {scene_no}: {scene_title}
Setting: {setting}
Beats: {beats}

Write the scene. Return JSON:
{{
 "scene_no": {scene_no},
 "scene_title": "{scene_title}",
 "lines": [
   {{"id": "s{scene_no}-l1", "who": "cast id or narration", "text": "Japanese line",
     "emo": "Japanese emotion tag", "sfx": "sound effect note or empty string"}}
 ],
 "outro_beat": "one sentence: how this scene hands off (Japanese)"
}}"""

# ---------------------------------------------------------------------------
# Director
# ---------------------------------------------------------------------------

DIRECT_SYSTEM = """You are the director of a Japanese audio-drama studio: a sharp,
practical script editor. You judge scripts by how they will SOUND, not how they read.

You are specific and unsentimental. You cite line ids. You never rewrite the whole
scene — you point at what is weak and why, so the writer can fix it."""

DIRECT_USER = """Script bible (abridged):
{bible_json}

Scene under review:
{scene_json}

Director notes from the human editor (may be empty):
{notes}

Review it. Return JSON:
{{
 "score": 0-10,
 "verdict": "one or two sentences (Japanese)",
 "issues": [
   {{"line_id": "...", "issue": "what is wrong (Japanese)",
     "fix": "concrete instruction for the rewrite (Japanese)"}}
 ],
 "pacing_note": "one sentence on flow (Japanese)",
 "keep": ["line ids that are strong"]
}}
Flag: flat exposition, lines that repeat information already given, characters
sounding identical, missing emotional turns, unperformable phrasing. 2-5 issues."""

REWRITE_SYSTEM = """You are the scriptwriter of a Japanese audio drama. The director has
sent specific notes; apply them with minimal changes. Keep the same line ids,
keep lines under 90 characters, keep each character's speech style."""

REWRITE_USER = """Story bible (abridged):
{bible_json}

Lines to rewrite (JSON):
{lines_json}

Director's instructions:
{notes}

Return JSON: {{"lines": [{{"id": "...", "who": "...", "text": "...", "emo": "...", "sfx": "..."}}]}}
Only include the rewritten lines, ids unchanged."""

# ---------------------------------------------------------------------------
# Continuity — episode summary
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM = """You maintain the series bible of a Japanese audio drama: after each
episode you compress what happened into the continuity notes the writing team needs."""

SUMMARY_USER = """Episode {episode_no} ({episode_title}) script:
{scene_texts}

Summarise. Return JSON:
{{
 "episode_summary": "3-4 sentences (Japanese)",
 "new_facts": ["plot facts established (Japanese)"],
 "open_threads": ["unresolved hooks (Japanese)"]
}}"""


class Agents:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def bible(self, premise: str, genre: str, tone: str, cast_size: int = 3) -> dict:
        u = BIBLE_USER.format(
            premise=premise, genre=genre, tone=tone, cast_size=cast_size
        )
        return self.llm.chat_json(BIBLE_SYSTEM, u, temperature=1.0, max_tokens=2400)

    def outline(self, bible: dict, prev_summary: str, episode_no: int = 1) -> dict:
        u = OUTLINE_USER.format(
            bible_json=_abridge_bible(bible),
            prev_summary=prev_summary or "(this is episode 1)",
            episode_no=episode_no,
        )
        return self.llm.chat_json(OUTLINE_SYSTEM, u, temperature=0.95, max_tokens=1800)

    def scene(
        self,
        bible: dict,
        episode_no: int,
        episode_title: str,
        scene: dict,
    ) -> dict:
        u = SCENE_USER.format(
            bible_json=_abridge_bible(bible),
            episode_no=episode_no,
            episode_title=episode_title,
            scene_no=scene.get("no", 1),
            scene_title=scene.get("title", ""),
            setting=scene.get("setting", ""),
            beats=scene.get("beats", ""),
        )
        return self.llm.chat_json(SCENE_SYSTEM, u, temperature=0.95, max_tokens=3200)

    def direct(self, bible: dict, scene: dict, notes: str = "") -> dict:
        u = DIRECT_USER.format(
            bible_json=_abridge_bible(bible),
            scene_json=_scene_for_prompt(scene),
            notes=notes or "(none)",
        )
        return self.llm.chat_json(DIRECT_SYSTEM, u, temperature=0.6, max_tokens=1800)

    def rewrite(self, bible: dict, lines: list, notes: str) -> list:
        import json as _json

        u = REWRITE_USER.format(
            bible_json=_abridge_bible(bible),
            lines_json=_json.dumps(lines, ensure_ascii=False),
            notes=notes,
        )
        out = self.llm.chat_json(REWRITE_SYSTEM, u, temperature=0.85, max_tokens=1800)
        return out.get("lines", [])

    def summarise(self, episode_no: int, episode_title: str, scene_texts: list[str]):
        u = SUMMARY_USER.format(
            episode_no=episode_no,
            episode_title=episode_title,
            scene_texts="\n\n".join(scene_texts)[:6000],
        )
        return self.llm.chat_json(SUMMARY_SYSTEM, u, temperature=0.5, max_tokens=1200)


# ---------------------------------------------------------------------------


def _abridge_bible(bible: dict) -> str:
    import json as _json

    keep = {k: bible.get(k) for k in ("title", "logline", "world", "cast", "series_hook")}
    return _json.dumps(keep, ensure_ascii=False)[:3500]


def _scene_for_prompt(scene: dict) -> str:
    import json as _json

    return _json.dumps(scene, ensure_ascii=False)[:4500]
