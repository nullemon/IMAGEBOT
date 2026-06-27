"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const FIELDS = ["title", "subtitle", "verb", "badges", "tag_main", "tag_sub", "date_text",
  "logo_style", "theme", "query", "image_url", "image_path", "logo_path",
  "focus_x", "focus_y", "zoom"];
const NEWS_FIELDS = ["headline", "body", "category", "source", "date_text",
  "theme", "query", "image_url", "image_path", "focus_x", "focus_y", "zoom"];
const RANK_FIELDS = ["rank", "name", "source", "query", "image_url", "image_path",
  "focus_x", "focus_y", "zoom"];

const LINEUP_PROMPT = `You are an anime-news researcher. Find 6 of the latest, notable anime announcements. (Topic: leave blank for trending, or specify e.g. "Anime Expo 2026 announcements".)

Output ONLY a plain list — one announcement per line, no numbering, no extra text — in this EXACT format:

Title | STATUS | DATE

Rules:
- Title: the official English series name only.
- STATUS: one of SEASON 4, MOVIE, NEW ARC, FINALE, NEW PV, NEW SERIES, GAME (pick the most fitting).
- DATE: a short date like "JULY 4" if there is one; otherwise omit it (just "Title | STATUS").

Example:
Attack on Titan | SEASON 4 | JUNE 19
Jujutsu Kaisen | MOVIE | JULY 3
Chainsaw Man | NEW ARC`;

const NEWS_PROMPT = `You are an anime-news editor. Find one notable, recent anime news story. (Topic: leave blank for trending, or specify e.g. "Attack on Titan".)

Output ONLY these lines, nothing else:

HEADLINE: <one punchy sentence, sentence case, no ALL CAPS>
CATEGORY: <NEWS | BREAKING | RELEASE DATE | TRAILER | NEW SEASON | MANGA | RANKING>
DATE: <short date like JULY 4, or leave blank>
SOURCE: <official source or @handle if known, else leave blank>

If it's a ranking / Top-list, also add:
ITEMS:
- first item
- second item
- third item`;

const RANK_PROMPT = `You are an anime-news researcher. Build a Top-N ranking like the Anime Corner cards. (Topic: e.g. "best girls of Spring 2026", or leave blank for trending.)

Output ONLY these lines, nothing else:

TITLE: <e.g. TOP 10 FEMALE CHARACTERS>
SUBTITLE: <e.g. BASED ON SPRING 2026 WEEK 11 (JUN 12 - JUN 19), or leave blank>
ITEMS:
1. <Name> — <Anime it's from>
2. <Name> — <Anime it's from>
3. <Name> — <Anime it's from>
... up to 10, best first.`;

const AUTO_PROMPT = `You are an anime-news researcher. Find one notable, recent anime/manga item (Topic: leave blank for trending, or name a series).

Just write it naturally — IMAGEBOT auto-detects the format and designs the card:
- a single story  → "Solo Leveling Season 3 premieres July 4"
- a few updates   → one per line: "Hunter x Hunter returns June 28", "Bleach Hell Arc leak — not yet official", "Berserk new chapters ongoing"
- a Top-N ranking → "TITLE: TOP 10 …" then "1. Name — Show" lines

No special formatting needed — paste it and hit Make.`;

let STATE = { mode: "auto", runid: "", styles: [], current: "" };
let ALL_EDITORS = [];
let NEWS_PE = null;

const clamp01 = (v) => Math.min(1, Math.max(0, isFinite(v) ? v : 0.5));
const clampZoom = (v) => Math.min(2.5, Math.max(1, isFinite(v) ? v : 1));
const SIZE_WH = { portrait: [1080, 1350], square: [1080, 1080], story: [1080, 1920], landscape: [1280, 720] };

// =========================================================================
//  interactive photo editor — drag to move, scroll / buttons to zoom.
//  Mirrors the server's cover-crop math so what you frame is what renders.
// =========================================================================
class PhotoEditor {
  constructor(canvas, fxEl, fyEl, zmEl, onChange, opts = {}) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.fxEl = fxEl; this.fyEl = fyEl; this.zmEl = zmEl; this.onChange = onChange;
    this.dfx = opts.dfx != null ? opts.dfx : 0.5;
    this.dfy = opts.dfy != null ? opts.dfy : 0.4;
    this.img = null; this.aspect = 1.6; this.dragging = false;
    this._bind(); this.resize();
  }
  fx() { return clamp01(parseFloat(this.fxEl.value)); }
  fy() { return clamp01(parseFloat(this.fyEl.value)); }
  zoom() { return clampZoom(parseFloat(this.zmEl.value)); }
  set(fx, fy, z) {
    this.fxEl.value = (+fx).toFixed(3); this.fyEl.value = (+fy).toFixed(3);
    this.zmEl.value = (+z).toFixed(2);
  }
  setAspect(a) { if (a > 0 && Math.abs(a - this.aspect) > 0.005) { this.aspect = a; this.resize(); } }
  resize() {
    const cw = Math.max(120, Math.round(this.cv.clientWidth || (this.cv.parentElement || {}).clientWidth || 320));
    const ch = Math.max(60, Math.round(cw / this.aspect));
    if (this.cv.width !== cw || this.cv.height !== ch) { this.cv.width = cw; this.cv.height = ch; }
    this.cv.style.height = ch + "px";
    this.draw();
  }
  setSrc(src) {
    if (!src) { this.img = null; this.draw(); return; }
    const im = new Image();
    im.onload = () => { this.img = im; this.draw(); };
    im.onerror = () => { this.img = null; this.draw(); };
    im.src = src;
  }
  geom() {
    const cw = this.cv.width, ch = this.cv.height;
    const iw = this.img.naturalWidth || 1, ih = this.img.naturalHeight || 1;
    const scale = Math.max(cw / iw, ch / ih) * this.zoom();
    const nw = iw * scale, nh = ih * scale;
    return { cw, ch, nw, nh, left: (nw - cw) * this.fx(), top: (nh - ch) * this.fy() };
  }
  draw() {
    const ctx = this.ctx, cw = this.cv.width, ch = this.cv.height;
    ctx.clearRect(0, 0, cw, ch);
    if (!this.img) {
      ctx.fillStyle = "#191c28"; ctx.fillRect(0, 0, cw, ch);
      ctx.fillStyle = "#7a8398"; ctx.font = "13px system-ui,sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("no image yet — find or upload art", cw / 2, ch / 2);
      this.cv.classList.add("empty"); return;
    }
    this.cv.classList.remove("empty");
    const g = this.geom();
    ctx.drawImage(this.img, -g.left, -g.top, g.nw, g.nh);
    ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, cw - 1, ch - 1);
  }
  _bind() {
    const cv = this.cv;
    cv.addEventListener("pointerdown", (e) => {
      if (!this.img) return;
      this.dragging = true; try { cv.setPointerCapture(e.pointerId); } catch (_) {}
      this.lx = e.clientX; this.ly = e.clientY; cv.classList.add("grabbing");
    });
    cv.addEventListener("pointermove", (e) => {
      if (!this.dragging || !this.img) return;
      const g = this.geom();
      const dx = e.clientX - this.lx, dy = e.clientY - this.ly;
      this.lx = e.clientX; this.ly = e.clientY;
      let fx = this.fx(), fy = this.fy();
      if (g.nw > g.cw) fx = clamp01((g.left - dx) / (g.nw - g.cw));
      if (g.nh > g.ch) fy = clamp01((g.top - dy) / (g.nh - g.ch));
      this.set(fx, fy, this.zoom()); this.draw();
    });
    const end = () => { if (this.dragging) { this.dragging = false; cv.classList.remove("grabbing"); this.commit(); } };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("wheel", (e) => {
      if (!this.img) return; e.preventDefault();
      this.set(this.fx(), this.fy(), clampZoom(this.zoom() * (e.deltaY < 0 ? 1.1 : 0.91)));
      this.draw(); this._cd();
    }, { passive: false });
  }
  zoomBy(f) { this.set(this.fx(), this.fy(), clampZoom(this.zoom() * f)); this.draw(); this.commit(); }
  reset() { this.set(this.dfx, this.dfy, 1); this.draw(); this.commit(); }
  commit() { if (this.onChange) this.onChange(); }
  _cd() { clearTimeout(this._t); this._t = setTimeout(() => this.commit(), 300); }
}

function curWH() { return SIZE_WH[($("#size") || {}).value || "portrait"] || SIZE_WH.portrait; }
function rankCount() { const n = $$("#rank-entries .rrow").length; return n || 10; }
function rankAspect(n) {
  const [W, H] = curWH();
  const hh = Math.min(Math.max(H * 0.11, 128), H * 0.17);
  const rowH = (H - hh) / Math.max(1, n || rankCount());
  return (W * 0.255) / rowH;
}
function lineupAspect() {
  const [W, H] = curWH();
  const ppc = Math.max(1, parseInt(($("#panels_per_card") || {}).value) || 4);
  return W / (H / ppc);
}
function newsAspect() { const [W, H] = curWH(); return W / H; }

function attachEditor(scope, kind, src, dfx, dfy) {
  const cont = scope.querySelector(`.photo-edit[data-edit="${kind}"]`) || scope.querySelector(".photo-edit");
  const cv = cont.querySelector(".pe-canvas");
  const fx = cont.querySelector('[data-f="focus_x"],[data-n="focus_x"],[data-e="focus_x"]');
  const fy = cont.querySelector('[data-f="focus_y"],[data-n="focus_y"],[data-e="focus_y"]');
  const zm = cont.querySelector('[data-f="zoom"],[data-n="zoom"],[data-e="zoom"]');
  const pe = new PhotoEditor(cv, fx, fy, zm, rerenderCurrent, { dfx, dfy });
  cont.querySelector(".pe-in").addEventListener("click", () => pe.zoomBy(1.12));
  cont.querySelector(".pe-out").addEventListener("click", () => pe.zoomBy(1 / 1.12));
  cont.querySelector(".pe-reset").addEventListener("click", () => pe.reset());
  pe.setAspect(kind === "rank" ? rankAspect() : kind === "panel" ? lineupAspect() : newsAspect());
  ALL_EDITORS.push(pe);
  if (src) pe.setSrc(src);
  requestAnimationFrame(() => pe.resize());
  return pe;
}

let _rerenderT;
function rerenderCurrent() {
  if (!STATE.current) return;
  clearTimeout(_rerenderT);
  _rerenderT = setTimeout(() => switchTemplate(STATE.current), 240);
}
function refreshAllAspects() {
  ALL_EDITORS = ALL_EDITORS.filter((pe) => document.contains(pe.cv));
  if (STATE.mode === "ranking") { const a = rankAspect(); $$("#rank-entries .rrow").forEach((r) => r._pe && r._pe.setAspect(a)); }
  else if (STATE.mode === "lineup") { const a = lineupAspect(); $$(".prow").forEach((r) => r._pe && r._pe.setAspect(a)); }
  else if (STATE.mode === "news" && NEWS_PE) NEWS_PE.setAspect(newsAspect());
}

const mode = () => (document.querySelector('input[name=mode]:checked') || {}).value || "auto";
function collectAccounts() {
  const accs = [];
  $$(".acc:checked").forEach((c) => accs.push({
    handle: c.value, watermark: c.dataset.wm || "", event_name: c.dataset.event || "",
  }));
  ($("#acc-extra").value || "").split(/[,\n]/).map((s) => s.trim()).filter(Boolean)
    .forEach((h) => accs.push({ handle: h.startsWith("@") ? h : "@" + h }));
  return accs.slice(0, 4);
}
function options() {
  return {
    mode: mode(),
    accounts: collectAccounts(),
    size: ($("#size") || {}).value || "portrait",
    provider: $("#provider").value,
    panels_per_card: $("#panels_per_card").value,
    event_name: $("#event_name").value,
    watermark: $("#watermark").value,
    date_text: $("#date_text").value,
    cover_title: $("#cover_title").value,
    find_art: $("#find_art").checked,
    vision_pick: $("#vision_pick").checked,
    clean_art: $("#clean_art").checked,
    find_logo: $("#find_logo").checked,
    ai_fallback: $("#ai_fallback").checked,
    write_caption: $("#write_caption").checked,
  };
}
function setBusy(on, msg) {
  const s = $("#status");
  s.classList.toggle("hidden", !on && !msg);
  if (on) s.innerHTML = `<span class="spinner"></span>${msg || "Working…"}`;
  else if (msg) s.textContent = msg;
  $("#generate").disabled = on;
  const rr = $("#rerender"); if (rr) rr.disabled = on;
}
const bust = (u) => u + (u.includes("?") ? "&" : "?") + "t=" + Date.now();
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok || !d.ok) throw new Error(d.error || "Request failed");
  return d;
}

// ---- template chips -------------------------------------------------------
function buildChips() {
  const box = $("#templates"); box.innerHTML = ""; box.classList.remove("hidden");
  STATE.styles.forEach((st) => {
    const c = document.createElement("button");
    c.className = "chip"; c.type = "button"; c.dataset.key = st.key; c.textContent = st.name;
    c.classList.toggle("active", st.key === STATE.current);
    c.addEventListener("click", () => switchTemplate(st.key));
    box.appendChild(c);
  });
}
const markActive = () => $$("#templates .chip").forEach((c) => c.classList.toggle("active", c.dataset.key === STATE.current));

async function switchTemplate(key) {
  STATE.current = key; markActive();
  const pc = $("#preview-cards"); pc.style.opacity = "0.45";
  try {
    const payload = { runid: STATE.runid, style: key, ...options(), mode: STATE.mode };
    if (STATE.mode === "news") payload.post = collectPost();
    else if (STATE.mode === "ranking") payload.ranking = collectRanking();
    else payload.panels = collectPanels();
    const d = await postJSON("/render_one", payload);
    showCurrent(d);
  } catch (e) { setBusy(false, "Error: " + e.message); }
  pc.style.opacity = "1";
}
function showCurrent(d) {
  STATE.current = d.key; if (d.runid) STATE.runid = d.runid;
  $("#preview-wrap").classList.remove("hidden");
  $("#cur-name").textContent = d.name;
  const pc = $("#preview-cards"); pc.innerHTML = "";
  (d.outputs || []).forEach((o) => o.cards.forEach((src, i) => {
    const div = document.createElement("div"); div.className = "sel-card";
    const label = o.account ? `<div class="acc-label">${o.account}</div>` : "";
    const name = (o.account || d.key).replace(/[^a-z0-9]/gi, "_");
    div.innerHTML = `${label}<img src="${bust(src)}"><a class="dl" href="${bust(src)}" download="${name}_${i + 1}.png">⬇ download</a>`;
    pc.appendChild(div);
  }));
  markActive();
}

// ---- result ---------------------------------------------------------------
function showResult(data) {
  STATE.mode = data.mode || "lineup";
  STATE.runid = data.runid; STATE.styles = data.styles; STATE.current = data.current ? data.current.key : "";
  ALL_EDITORS = ALL_EDITORS.filter((pe) => document.contains(pe.cv));
  $("#empty").classList.add("hidden");
  // auto mode resolved to a concrete mode (radio stays on ✨ Auto; STATE.mode
  // tracks what it became so edits/switches route correctly)
  const an = $("#auto-note");
  if (data.auto) {
    an.textContent = "✨ Auto-picked: " + data.auto + " — tweak below, or switch templates / mode to override.";
    an.classList.remove("hidden");
  } else { an.classList.add("hidden"); }
  $("#run-note").textContent = `run ${data.runid} · ${data.styles.length} templates · ${data.provider_used}`;
  $("#provider-note").textContent = "provider: " + data.provider_used;
  $("#dl-zip").classList.toggle("hidden", STATE.mode !== "lineup");
  buildChips();

  const w = $("#warnings"); w.innerHTML = "";
  (data.warnings || []).forEach((x) => { const li = document.createElement("li"); li.textContent = x; w.appendChild(li); });
  if (data.caption) { $("#caption-wrap").classList.remove("hidden"); $("#caption").value = data.caption; }

  $("#editor").classList.remove("hidden");
  const isLineup = STATE.mode === "lineup", isNews = STATE.mode === "news", isRank = STATE.mode === "ranking";
  $("#panels").classList.toggle("hidden", !isLineup);
  $("#add-panel").classList.toggle("hidden", !isLineup);
  $("#news-fields").classList.toggle("hidden", !isNews);
  $("#rank-fields").classList.toggle("hidden", !isRank);

  if (isLineup) { $("#panels").innerHTML = ""; (data.panels || []).forEach(addPanel); }
  else if (isNews) populateNews(data.post || {});
  else if (isRank) populateRanking(data.ranking || {});

  if (data.current) showCurrent(data.current);
}

// ---- news editor ----------------------------------------------------------
function populateNews(post) {
  NEWS_FIELDS.forEach((f) => { const el = $(`[data-n="${f}"]`); if (el) el.value = post[f] || ""; });
  $("#news-art-state").textContent = post.image_path ? "✓ art set" : "";
  if (!NEWS_PE) NEWS_PE = attachEditor($("#news-fields"), "news", "", 0.5, 0.4);
  NEWS_PE.setAspect(newsAspect());
  NEWS_PE.setSrc(post.art_url || "");
  requestAnimationFrame(() => NEWS_PE.resize());
}
function collectPost() {
  const p = {}; NEWS_FIELDS.forEach((f) => { const el = $(`[data-n="${f}"]`); if (el) p[f] = el.value; });
  return p;
}

// ---- lineup editor --------------------------------------------------------
function buildRow(panel) {
  const row = $("#panel-row").content.cloneNode(true).querySelector(".prow");
  FIELDS.forEach((f) => {
    const el = row.querySelector(`[data-f="${f}"]`);
    if (el && panel[f] != null) el.value = Array.isArray(panel[f]) ? panel[f].join(", ") : panel[f];
  });
  if (panel.logo_path) row.querySelector(".art-state").textContent = "✓ logo";
  const pe = attachEditor(row, "panel", panel.art_url || "", 0.6, 0.4);
  row._pe = pe;
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove(); refreshAllAspects(); if (!$$(".prow").length) $("#editor").classList.add("hidden");
  });
  row.querySelector(".art-file").addEventListener("change", (e) => {
    const file = e.target.files[0]; if (!file) return;
    pe.setSrc(URL.createObjectURL(file));
    uploadFile("/upload", file, {}, row.querySelector(".art-state"), row.querySelector('[data-f="image_path"]'),
      "✓ custom art", () => rerenderCurrent());
  });
  row.querySelector(".logo-file").addEventListener("change", (e) =>
    uploadFile("/upload_logo", e.target.files[0], { title: row.querySelector('[data-f="title"]').value },
      row.querySelector(".art-state"), row.querySelector('[data-f="logo_path"]'), "✓ logo", () => rerenderCurrent()));
  row.querySelector(".find-logo").addEventListener("click", async () => {
    const title = row.querySelector('[data-f="title"]').value.trim(); if (!title) return;
    const state = row.querySelector(".art-state"); state.textContent = "searching logo…";
    try {
      const d = await postJSON("/find_logo", { title, provider: $("#provider").value });
      row.querySelector('[data-f="logo_path"]').value = d.logo_path; state.textContent = "✓ logo"; rerenderCurrent();
    } catch (e) { state.textContent = "no logo found"; }
  });
  row.querySelector('[data-f="image_url"]').addEventListener("change", (e) => {
    const u = e.target.value.trim(); if (u) pe.setSrc(u);
  });
  return row;
}
async function uploadFile(url, file, extra, stateEl, targetEl, okMsg, cb) {
  if (!file) return;
  if (stateEl) stateEl.textContent = "uploading…";
  const fd = new FormData(); fd.append("file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  try {
    const r = await fetch(url, { method: "POST", body: fd });
    const d = await r.json(); if (!d.ok) throw new Error(d.error);
    if (targetEl) targetEl.value = d.image_path || d.logo_path;
    if (stateEl) stateEl.textContent = okMsg;
    if (cb) cb(d);
  } catch (e) { if (stateEl) stateEl.textContent = "upload failed"; }
}
function addPanel(panel = { title: "" }) { $("#panels").appendChild(buildRow(panel)); refreshAllAspects(); }
function collectPanels() {
  return $$(".prow").map((row) => {
    const p = {}; FIELDS.forEach((f) => { const el = row.querySelector(`[data-f="${f}"]`); if (el) p[f] = el.value; });
    return p;
  }).filter((p) => p.title.trim());
}

// ---- ranking editor -------------------------------------------------------
function renumberRanks() {
  $$("#rank-entries .rrow").forEach((r, i) => {
    r.querySelector(".rrow-num").textContent = i + 1;
    const rk = r.querySelector('[data-e="rank"]'); if (rk) rk.value = i + 1;
  });
}
function buildRankRow(entry) {
  const row = $("#rank-row").content.cloneNode(true).querySelector(".rrow");
  RANK_FIELDS.forEach((f) => { const el = row.querySelector(`[data-e="${f}"]`); if (el && entry[f] != null) el.value = entry[f]; });
  const pe = attachEditor(row, "rank", entry.art_url || "", 0.5, 0.32);
  row._pe = pe;
  row.querySelector(".art-file").addEventListener("change", (e) => {
    const file = e.target.files[0]; if (!file) return;
    pe.setSrc(URL.createObjectURL(file));
    uploadFile("/upload", file, {}, row.querySelector(".art-state"), row.querySelector('[data-e="image_path"]'),
      "✓ custom art", () => rerenderCurrent());
  });
  row.querySelector('[data-e="image_url"]').addEventListener("change", (e) => {
    const u = e.target.value.trim(); if (u) pe.setSrc(u);
  });
  row.querySelector(".remove").addEventListener("click", () => { row.remove(); renumberRanks(); refreshAllAspects(); rerenderCurrent(); });
  return row;
}
function addRankRow(entry = {}) { $("#rank-entries").appendChild(buildRankRow(entry)); renumberRanks(); }
function populateRanking(rl) {
  $('[data-r="title"]').value = rl.title || "";
  $('[data-r="subtitle"]').value = rl.subtitle || "";
  $('[data-r="logo_path"]').value = rl.logo_path || "";
  updateRankLogo(rl.logo_url || "");
  const box = $("#rank-entries"); box.innerHTML = "";
  (rl.entries || []).forEach(addRankRow);
  refreshAllAspects();
}
function collectRanking() {
  const entries = $$("#rank-entries .rrow").map((row, i) => {
    const e = {}; RANK_FIELDS.forEach((f) => { const el = row.querySelector(`[data-e="${f}"]`); if (el) e[f] = el.value; });
    e.rank = i + 1;
    return e;
  }).filter((e) => (e.name || "").trim());
  return {
    title: ($('[data-r="title"]') || {}).value || "TOP 10",
    subtitle: ($('[data-r="subtitle"]') || {}).value || "",
    logo_path: ($('[data-r="logo_path"]') || {}).value || "",
    entries,
  };
}
function updateRankLogo(url) {
  const img = $("#rank-logo-prev"), fb = $("#rank-logo-fallback");
  if (url) { img.src = url; img.classList.remove("hidden"); fb.classList.add("hidden"); }
  else { img.classList.add("hidden"); img.removeAttribute("src"); fb.classList.remove("hidden"); }
}

// ---- actions --------------------------------------------------------------
async function generate() {
  const news = $("#news").value.trim();
  if (!news) { setBusy(false, "Paste some news first."); return; }
  setBusy(true, "Parsing, finding art, building your card…");
  try { const d = await postJSON("/generate", { news, style: STATE.current, ...options() }); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}
async function applyEdits() {
  setBusy(true, "Applying edits & refreshing art…");
  const payload = { style: STATE.current, runid: STATE.runid, ...options(), mode: STATE.mode };
  if (STATE.mode === "news") payload.post = collectPost();
  else if (STATE.mode === "ranking") payload.ranking = collectRanking();
  else payload.panels = collectPanels();
  try { const d = await postJSON("/render", payload); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}
async function downloadZip() {
  if (!STATE.current || STATE.mode !== "lineup") return;
  setBusy(true, "Building carousel…");
  try {
    const d = await postJSON("/carousel", { panels: collectPanels(), runid: STATE.runid, style: STATE.current, cover: $("#cover").checked, ...options() });
    setBusy(false, "Carousel ready.");
    const a = document.createElement("a"); a.href = bust(d.zip); a.download = `${STATE.current}_carousel.zip`;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { setBusy(false, "Error: " + e.message); }
}

function onModeChange() {
  const m = mode();
  $("#news").placeholder = m === "ranking"
    ? "Paste your list, e.g.\nTITLE: TOP 10 FEMALE CHARACTERS\nSUBTITLE: BASED ON SPRING 2026 WEEK 11\nITEMS:\n1. Frieren — Frieren: Beyond Journey's End\n2. Anya Forger — Spy x Family\n3. Power — Chainsaw Man"
    : m === "news"
      ? "Paste one news story, e.g.\nAttack on Titan Final Season gets a new trailer at Anime Expo — out July 4"
      : m === "lineup"
        ? "One announcement per line, e.g.\nAttack on Titan Season 4 new info — June 19\nJujutsu Kaisen movie — July 3"
        : "Paste ANYTHING — one story, a few updates, or a Top-10 list. IMAGEBOT detects the type and designs it.\n\ne.g.\nHunter x Hunter returns June 28\nBleach Hell Arc — leak, not yet official\nBerserk new chapters ongoing";
  $("#ai-prompt").value = m === "ranking" ? RANK_PROMPT : m === "news" ? NEWS_PROMPT : m === "lineup" ? LINEUP_PROMPT : AUTO_PROMPT;
  ["#templates", "#preview-wrap", "#editor"].forEach((s) => $(s).classList.add("hidden"));
  $("#auto-note").classList.add("hidden");
  $("#empty").classList.remove("hidden");
}

// ---- wiring ---------------------------------------------------------------
$("#copy-prompt").addEventListener("click", () => {
  navigator.clipboard.writeText($("#ai-prompt").value);
  const b = $("#copy-prompt"); b.textContent = "Copied!";
  setTimeout(() => (b.textContent = "Copy prompt"), 1500);
});
$$('input[name=mode]').forEach((r) => r.addEventListener("change", onModeChange));
$("#generate").addEventListener("click", generate);
$("#rerender").addEventListener("click", applyEdits);
$("#add-panel").addEventListener("click", () => addPanel());
$("#dl-zip").addEventListener("click", downloadZip);

$("#add-entry")?.addEventListener("click", () => { addRankRow({}); refreshAllAspects(); });
$("#rank-logo")?.addEventListener("change", (e) => {
  const file = e.target.files[0]; if (!file) return;
  updateRankLogo(URL.createObjectURL(file));
  uploadFile("/upload", file, {}, null, $('[data-r="logo_path"]'), "", (d) => { updateRankLogo(bust(d.url)); rerenderCurrent(); });
});
$("#rank-logo-clear")?.addEventListener("click", () => { $('[data-r="logo_path"]').value = ""; updateRankLogo(""); rerenderCurrent(); });

$("#news-art")?.addEventListener("change", (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (NEWS_PE) NEWS_PE.setSrc(URL.createObjectURL(f));
  uploadFile("/upload", f, {}, $("#news-art-state"), $('[data-n="image_path"]'), "✓ art set", () => rerenderCurrent());
});
$('[data-n="image_url"]')?.addEventListener("change", (e) => { const u = e.target.value.trim(); if (u && NEWS_PE) NEWS_PE.setSrc(u); });

$("#size")?.addEventListener("change", () => { refreshAllAspects(); rerenderCurrent(); });
$("#panels_per_card")?.addEventListener("change", () => { refreshAllAspects(); });

$("#copy-caption").addEventListener("click", () => {
  navigator.clipboard.writeText($("#caption").value);
  $("#copy-caption").textContent = "Copied!"; setTimeout(() => ($("#copy-caption").textContent = "Copy"), 1500);
});
$("#news").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate(); });

let _rt;
window.addEventListener("resize", () => {
  clearTimeout(_rt);
  _rt = setTimeout(() => {
    ALL_EDITORS = ALL_EDITORS.filter((pe) => document.contains(pe.cv));
    ALL_EDITORS.forEach((pe) => pe.resize());
  }, 200);
});

onModeChange();
