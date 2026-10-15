/* Kataribe Studio — studio front-end.
   All state lives here; every AI action is one POST to the local studio server,
   which routes it to the active inference provider (AMD or dev). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const api = async (path, body) => {
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
};

const state = {
  bible: null, cast: [], voices: {},
  outline: null, episodeNo: 1, episodeTitle: "",
  scene: null,          // {scene_no, scene_title, lines:[], outro_beat}
  sceneMeta: null,      // outline scene entry
  audio: {},            // line id -> {path, cached}
  director: null,
  rendered: null,
  history: [],          // continuity summaries
  busy: 0,
};

/* ---------------- chrome ---------------- */

function feed(msg) {
  const t = new Date().toTimeString().slice(0, 8);
  const el = document.createElement("div");
  el.textContent = `[${t}] ${msg}`;
  $("#feed").prepend(el);
}

function busy(on, text) {
  state.busy += on ? 1 : -1;
  state.busy = Math.max(0, state.busy);
  $("#busyNote").classList.toggle("hidden", state.busy === 0);
  if (text) $("#busyText").textContent = text;
}

function progress(p) { $("#progBar").style.width = `${Math.round(p * 100)}%`; }

function toast(msg, ms = 5200) {
  const el = document.createElement("div");
  el.className = "overlay-note";
  el.style.borderColor = "#ff8a1e";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ms);
}


async function refreshStatus() {
  const st = await api("/api/status");
  const act = st.active;
  const cfg = st[act];
  const ok = cfg.configured;
  $("#amdBadge").className = "badge " + (act === "amd" ? (ok ? "ok" : "live") : "ok");
  $("#amdBadgeText").textContent = act === "amd"
    ? (ok ? `AMD Instinct online · ${cfg.model || "model"}` : "AMD endpoint not configured — using dev")
    : `dev endpoint · ${cfg.model || ""}`;
  const u = cfg.usage;
  $("#usageText").textContent = `calls ${u.calls} · ${(u.prompt_tokens + u.completion_tokens).toLocaleString()} tok · ${u.avg_latency_ms} ms`;
  $("#stCalls").textContent = u.calls;
  $("#stTokens").textContent = (u.prompt_tokens + u.completion_tokens).toLocaleString();
  $("#stLat").textContent = u.avg_latency_ms;
  $("#stErr").textContent = u.errors;
  $("#modelInfo").textContent = `${cfg.label}${cfg.model ? " · model " + cfg.model : ""}`;
  $("#footProvider").textContent = cfg.label;
  $("#providerSel").value = act;
  if (st.provider_locked) {
    // hosted demo: the provider is fixed so every visitor runs on the AMD endpoint
    $("#providerSel").style.display = "none";
  }
}

async function loadSeriesList() {
  const d = await api("/api/series");
  const box = $("#seriesList");
  box.innerHTML = "";
  if (!d.series.length) box.innerHTML = '<div class="hint">no saved series yet</div>';
  for (const s of d.series) {
    const el = document.createElement("div");
    el.className = "ep-item";
    el.innerHTML = `<span class="t">${esc(s.title)}</span><span class="tag">ep ${s.episodes}</span>`;
    el.style.cursor = "pointer";
    el.onclick = async () => {
      const full = await api(`/api/episodes/${s.id}`);
      state.bible = full.bible; state.outline = full.outline || null;
      state.history = full.history || [];
      state.episodeNo = (full.episodes?.length || 0) + 1;
      renderBible(); renderOutline();
      feed(`series loaded: ${full.bible?.title || s.id}`);
    };
    box.appendChild(el);
  }
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------- writers' room ---------------- */

async function doBible() {
  busy(true, "Scriptwriter is developing the story bible…");
  try {
    const bible = await api("/api/bible", {
      premise: $("#premise").value.trim(),
      genre: $("#genre").value,
      tone: $("#tone").value,
      cast_size: parseInt($("#castSize").value, 10),
    });
    state.bible = bible;
    state.cast = bible.cast || [];
    const vf = await api("/api/voices_for", { cast: state.cast, scene: {} });
    state.voices = Object.fromEntries(vf.voices.map((v) => [v.id, v]));
    renderBible();
    $("#btnOutline").disabled = false;
    feed(`bible: 「${bible.title}」 cast=${state.cast.length} (model: ${(await api("/api/status")).active})`);
    await refreshStatus();
  } catch (e) { feed("ERROR bible: " + e.message); toast("Model error: " + e.message); }
  finally { busy(false); }
}

function colorFor(id) {
  let h = 0;
  for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 70% 62%)`;
}

function renderBible() {
  if (!state.bible) return;
  $("#bibleCard").classList.remove("hidden");
  $("#bibleTitle").textContent = state.bible.title || "";
  $("#bibleLogline").textContent = state.bible.logline || "";
  $("#bibleWorld").textContent = state.bible.world || "";
  $("#bibleHook").textContent = state.bible.series_hook ? "hook: " + state.bible.series_hook : "";
  const box = $("#castList");
  box.innerHTML = "";
  for (const ch of state.cast) {
    const v = state.voices[ch.id] || {};
    const el = document.createElement("div");
    el.className = "castcard";
    el.innerHTML = `
      <div class="avatar" style="background:${colorFor(ch.id)}">${esc((ch.name || "?").slice(0, 1))}</div>
      <div class="meta"><b>${esc(ch.name)}</b><small>${esc(ch.role || "")} · ${esc(ch.speech_style || "")}</small></div>
      <div class="voicetag">${esc((v.voice || "").replace("ja-JP-", "").replace("Neural", ""))}<br>r${v.rate ?? ""} p${v.pitch ?? ""}</div>`;
    box.appendChild(el);
  }
}

async function doOutline() {
  busy(true, "Scriptwriter is planning the episode…");
  try {
    const outline = await api("/api/outline", {
      bible: state.bible,
      prev_summary: state.history.slice(-1).map((h) => h.episode_summary).join("\n") || "",
      episode_no: parseInt($("#epNo").value || "1", 10),
    });
    state.outline = outline;
    state.episodeNo = parseInt($("#epNo").value || "1", 10);
    state.episodeTitle = outline.episode_title || "";
    renderOutline();
    feed(`outline ep${state.episodeNo}: 「${outline.episode_title}」 ${outline.scenes?.length || 0} scenes`);
    await refreshStatus();
  } catch (e) { feed("ERROR outline: " + e.message); toast("Model error: " + e.message); }
  finally { busy(false); }
}

function renderOutline() {
  const box = $("#outlineList");
  box.innerHTML = "";
  if (!state.outline) return;
  const head = document.createElement("div");
  head.className = "hint mb";
  head.textContent = `ep ${state.episodeNo}: ${state.outline.episode_title}`;
  box.appendChild(head);
  (state.outline.scenes || []).forEach((sc) => {
    const el = document.createElement("div");
    el.className = "ep-item";
    el.innerHTML = `<span class="t">S${sc.no} ${esc(sc.title)}</span><button class="sm">open</button>`;
    el.querySelector("button").onclick = () => openScene(sc);
    box.appendChild(el);
  });
  const cliff = document.createElement("div");
  cliff.className = "hint mt";
  cliff.textContent = "cliffhanger: " + (state.outline.cliffhanger || "");
  box.appendChild(cliff);
}

/* ---------------- scene desk ---------------- */

function openScene(sc) {
  state.sceneMeta = sc;
  state.scene = null;
  state.audio = {};
  state.director = null;
  $("#sceneEmpty").classList.add("hidden");
  $("#sceneWrap").classList.remove("hidden");
  $("#sceneTitle").textContent = `S${sc.no} · ${sc.title}`;
  $("#sceneTag").textContent = sc.setting || "";
  $("#sceneOutro").textContent = "";
  $("#lineList").innerHTML = '<div class="hint" style="padding:12px">Press “Draft scene with scriptwriter”.</div>';
  $("#directorCard").style.display = "none";
  $("#btnApply").disabled = true;
  $("#btnVoice").disabled = true;
  $("#btnRender").disabled = true;
  $("#playerCard").classList.add("hidden");
}

async function doDraft() {
  busy(true, "Scriptwriter is drafting the scene…");
  try {
    const scene = await api("/api/scene", {
      bible: state.bible, episode_no: state.episodeNo,
      episode_title: state.episodeTitle, scene: state.sceneMeta,
    });
    state.scene = scene; state.audio = {};
    renderScene();
    $("#btnVoice").disabled = false;
    feed(`scene script: ${scene.lines?.length || 0} lines`);
    await refreshStatus();
  } catch (e) { feed("ERROR scene: " + e.message); toast("Model error: " + e.message); }
  finally { busy(false); }
}

function renderScene() {
  const box = $("#lineList");
  box.innerHTML = "";
  $("#sceneTitle").textContent = `S${state.scene.scene_no ?? ""} · ${state.scene.scene_title || ""}`;
  $("#sceneOutro").textContent = state.scene.outro_beat || "";
  (state.scene.lines || []).forEach((ln, idx) => {
    const el = document.createElement("div");
    el.className = "line" + (ln.who === "narration" ? " narration" : "");
    el.dataset.id = ln.id;
    el.innerHTML = `
      <div class="who ${ln.who === "narration" ? "is-narration" : ""}">${esc(ln.who)}</div>
      <textarea class="text" rows="2">${esc(ln.text)}</textarea>
      <input class="emo" value="${esc(ln.emo || "")}" title="emotion"/>
      <input class="sfx" value="${esc(ln.sfx || "")}" title="sfx"/>
      <div class="tools"></div>
      <div class="audio-cell"></div>`;
    const tools = el.querySelector(".tools");
    const bResynth = document.createElement("button");
    bResynth.className = "sm"; bResynth.textContent = "♪";
    bResynth.title = "re-synthesize this line";
    bResynth.onclick = () => synthOne(ln);
    const bDel = document.createElement("button");
    bDel.className = "sm"; bDel.textContent = "✕"; bDel.title = "delete line";
    bDel.onclick = () => { state.scene.lines.splice(idx, 1); renderScene(); };
    tools.append(bResynth, bDel);
    el.querySelector(".text").addEventListener("input", (ev) => { ln.text = ev.target.value; });
    el.querySelector(".emo").addEventListener("input", (ev) => { ln.emo = ev.target.value; });
    el.querySelector(".sfx").addEventListener("input", (ev) => { ln.sfx = ev.target.value; });
    box.appendChild(el);
    if (state.audio[ln.id]) attachAudio(el.querySelector(".audio-cell"), ln.id);
  });
}

function attachAudio(cell, id) {
  const a = state.audio[id];
  if (!a) return;
  // audio src comes from our own server (/api/audio_proxy) — no user content in URL
  cell.innerHTML = `<audio controls preload="none" src="${a.url}"></audio>`;
}

/* ---------------- director ---------------- */

async function doDirect() {
  if (!state.scene) return;
  busy(true, "Director is reviewing the scene…");
  try {
    const d = await api("/api/direct", {
      bible: state.bible, scene: state.scene, notes: $("#dirNotes").value.trim(),
    });
    state.director = d;
    renderDirector();
    feed(`director: score ${d.score}/10, ${d.issues?.length || 0} issues`);
    await refreshStatus();
  } catch (e) { feed("ERROR director: " + e.message); toast("Model error: " + e.message); }
  finally { busy(false); }
}

function renderDirector() {
  const d = state.director;
  $("#directorCard").style.display = "block";
  $("#dirScore").textContent = `${d.score}/10`;
  $("#dirVerdict").textContent = d.verdict || "";
  const box = $("#dirIssues");
  box.innerHTML = "";
  (d.issues || []).forEach((iss) => {
    const el = document.createElement("div");
    el.className = "issue";
    el.innerHTML = `<b>${esc(iss.line_id)}</b> — ${esc(iss.issue)}<div class="fix">fix: ${esc(iss.fix)}</div>`;
    box.appendChild(el);
  });
  const p = document.createElement("div");
  p.className = "hint mt"; p.textContent = "pacing: " + (d.pacing_note || "");
  box.appendChild(p);
  $("#btnApply").disabled = !(d.issues || []).length;
  // highlight flagged lines
  document.querySelectorAll(".line").forEach((el) => el.classList.remove("hot"));
  (d.issues || []).forEach((iss) => {
    const el = document.querySelector(`.line[data-id="${CSS.escape(iss.line_id)}"]`);
    if (el) el.classList.add("hot");
  });
}

async function doApply() {
  const d = state.director;
  if (!d || !d.issues?.length) return;
  const ids = d.issues.map((i) => i.line_id);
  const lines = state.scene.lines.filter((l) => ids.includes(l.id));
  const notes = d.issues.map((i) => `line ${i.line_id}: ${i.issue} → ${i.fix}`).join("\n")
    + ($("#dirNotes").value.trim() ? "\nEditor notes: " + $("#dirNotes").value.trim() : "");
  busy(true, "Scriptwriter is applying the director's notes…");
  try {
    const out = await api("/api/rewrite", { bible: state.bible, lines, notes });
    for (const rl of out.lines || []) {
      const cur = state.scene.lines.find((l) => l.id === rl.id);
      if (cur) Object.assign(cur, rl);
    }
    renderScene();
    feed(`rewrote ${out.lines?.length || 0} lines from director notes`);
    await refreshStatus();
  } catch (e) { feed("ERROR rewrite: " + e.message); toast("Model error: " + e.message); }
  finally { busy(false); }
}

/* ---------------- voice booth ---------------- */

async function doVoice() {
  if (!state.scene) return;
  busy(true, "Voice booth: synthesizing lines…");
  progress(0.05);
  try {
    const out = await api("/api/voice", { scene: state.scene, cast: state.cast });
    const map = out.lines || [];
    progress(1);
    for (const a of map) {
      state.audio[a.id] = { path: a.path, url: a.url, cached: a.cached };
      const cell = document.querySelector(`.line[data-id="${CSS.escape(a.id)}"] .audio-cell`);
      if (cell) attachAudio(cell, a.id);
    }
    $("#btnRender").disabled = false;
    feed(`voices: ${map.length} lines (${out.synthesized} newly synthesised, ${map.length - out.synthesized} cached)`);
  } catch (e) { feed("ERROR voice: " + e.message); toast("Voice error: " + e.message); }
  finally { busy(false); setTimeout(() => progress(0), 800); }
}

async function synthOne(ln) {
  busy(true, `re-synthesizing ${ln.id}…`);
  try {
    const out = await api("/api/voice", { scene: { lines: [ln] }, cast: state.cast });
    for (const a of out.lines || []) {
      state.audio[a.id] = { path: a.path, url: a.url, cached: a.cached };
      const cell = document.querySelector(`.line[data-id="${CSS.escape(a.id)}"] .audio-cell`);
      if (cell) attachAudio(cell, a.id);
    }
    feed(`re-synth ${ln.id}: ${out.lines?.[0]?.voice || ""} ${out.lines?.[0]?.cached ? "(cached)" : ""}`);
  } catch (e) { feed("ERROR voice: " + e.message); }
  finally { busy(false); }
}

async function doRender() {
  if (!state.scene) return;
  const scenes = [{ lines: state.scene.lines.map((l) => ({ id: l.id, path: state.audio[l.id]?.path || "", text: l.text, who: l.who })) }];
  busy(true, "Mixing the episode (ffmpeg)…");
  try {
    const name = `ep${state.episodeNo}-${(state.episodeTitle || "episode")}`;
    const info = await api("/api/render", { scenes, out_name: name });
    state.rendered = info;
    $("#playerCard").classList.remove("hidden");
    $("#player").src = info.url + "?t=" + Date.now();
    $("#downloadMp3").href = info.url;
    $("#renderInfo").textContent = `${info.duration}s · ${info.lines} lines`;
    feed(`master: ${info.duration}s → ${info.url}`);
    // snapshot so the session can be resumed (and replayed for demos)
    const audioPaths = Object.fromEntries(Object.entries(state.audio).map(([k, v]) => [k, v.path]));
    await api("/api/episode/save", {
      bible: state.bible, outline: state.outline || {}, episode_no: state.episodeNo,
      episode_title: state.episodeTitle, scene: state.scene, audio: audioPaths,
      mp3: new URL(info.url, location.origin).origin === location.origin ? info.url : "",
    }).catch(() => {});
  } catch (e) { feed("ERROR render: " + e.message); toast("Render error: " + e.message); }
  finally { busy(false); }
}

window.__loadDemo = async function () {
  try {
    const ep = await api("/api/demo/last");
    state.bible = ep.bible; state.cast = ep.bible.cast || [];
    state.outline = ep.outline || null;
    state.episodeNo = ep.episode_no || 1; state.episodeTitle = ep.episode_title || "";
    state.scene = ep.scene || null;
    state.audio = {};
    for (const [lid, a] of Object.entries(ep.audio_resolved || {})) {
      state.audio[lid] = { path: a.path, url: a.url, cached: true };
    }
    const vf = await api("/api/voices_for", { cast: state.cast, scene: {} });
    state.voices = Object.fromEntries(vf.voices.map((v) => [v.id, v]));
    renderBible();
    $("#btnOutline").disabled = false;
    renderOutline();
    if (state.scene) {
      $("#sceneEmpty").classList.add("hidden");
      $("#sceneWrap").classList.remove("hidden");
      renderScene();
      $("#btnVoice").disabled = false;
      $("#btnRender").disabled = false;
    }
    if (ep.mp3_url) {
      state.rendered = { url: ep.mp3_url };
      $("#playerCard").classList.remove("hidden");
      $("#player").src = ep.mp3_url;
      $("#downloadMp3").href = ep.mp3_url;
      $("#renderInfo").textContent = "last master";
    }
    feed("session restored from last episode");
    return true;
  } catch (e) { return false; }
};

/* ---------------- series save ---------------- */

async function saveSeries() {
  if (!state.bible) return toast("develop the story bible first");
  busy(true, "Continuity agent is writing the episode summary…");
  try {
    const sceneTexts = (state.scene?.lines || []).map((l) => `${l.who}: ${l.text}`);
    let sum = null;
    if (sceneTexts.length) {
      sum = await api("/api/summary", {
        episode_no: state.episodeNo, episode_title: state.episodeTitle, scene_texts: sceneTexts,
      });
      state.history.push(sum);
    }
    const series = {
      id: state.seriesId || undefined,
      bible: state.bible,
      outline: state.outline,
      history: state.history,
      episodes: (state.outline?.scenes || []).map((s) => ({ no: s.no, title: s.title })),
    };
    const r = await api("/api/series/save", { series });
    state.seriesId = r.id;
    feed(`series saved (${r.id})`);
    await loadSeriesList();
    await refreshStatus();
  } catch (e) { feed("ERROR save: " + e.message); }
  finally { busy(false); }
}

/* ---------------- wire up ---------------- */

$("#btnBible").onclick = doBible;
$("#btnOutline").onclick = doOutline;
$("#btnDraft").onclick = doDraft;
$("#btnDirect").onclick = doDirect;
$("#btnApply").onclick = doApply;
$("#btnRevise").onclick = doDirect;
$("#btnVoice").onclick = doVoice;
$("#btnRender").onclick = doRender;
$("#btnSave").onclick = saveSeries;
$("#btnLoad").onclick = loadSeriesList;
$("#providerSel").onchange = async (e) => {
  await api("/api/provider", { provider: e.target.value });
  feed("provider → " + e.target.value);
  await refreshStatus();
};

refreshStatus().catch(() => {});
loadSeriesList().catch(() => {});
feed("studio ready");
setInterval(() => refreshStatus().catch(() => {}), 5000);
// restore the last working session if one exists (nice for demos & continuity)
setTimeout(() => { window.__loadDemo && window.__loadDemo(); }, 800);
