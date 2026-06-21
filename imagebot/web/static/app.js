"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const FIELDS = ["title", "subtitle", "tag_main", "tag_sub", "date_text",
  "logo_style", "theme", "query", "image_url", "image_path", "logo_path"];
const NEWS_FIELDS = ["headline", "body", "category", "source", "date_text",
  "theme", "query", "image_url", "image_path"];

let STATE = { mode: "lineup", runid: "", styles: [], current: "" };

const mode = () => (document.querySelector('input[name=mode]:checked') || {}).value || "lineup";
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
    const payload = { runid: STATE.runid, style: key, ...options() };
    if (STATE.mode === "news") payload.post = collectPost(); else payload.panels = collectPanels();
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
  $("#empty").classList.add("hidden");
  $("#run-note").textContent = `run ${data.runid} · ${data.styles.length} templates · ${data.provider_used}`;
  $("#provider-note").textContent = "provider: " + data.provider_used;
  $("#dl-zip").classList.toggle("hidden", STATE.mode === "news");
  buildChips();

  const w = $("#warnings"); w.innerHTML = "";
  (data.warnings || []).forEach((x) => { const li = document.createElement("li"); li.textContent = x; w.appendChild(li); });
  if (data.caption) { $("#caption-wrap").classList.remove("hidden"); $("#caption").value = data.caption; }
  if (data.current) showCurrent(data.current);

  $("#editor").classList.remove("hidden");
  if (STATE.mode === "news") {
    $("#panels").classList.add("hidden"); $("#add-panel").classList.add("hidden");
    $("#news-fields").classList.remove("hidden");
    populateNews(data.post || {});
  } else {
    $("#news-fields").classList.add("hidden");
    $("#panels").classList.remove("hidden"); $("#add-panel").classList.remove("hidden");
    $("#panels").innerHTML = ""; (data.panels || []).forEach(addPanel);
  }
}

// ---- news editor ----------------------------------------------------------
function populateNews(post) {
  NEWS_FIELDS.forEach((f) => { const el = $(`[data-n="${f}"]`); if (el) el.value = post[f] || ""; });
  $("#news-art-state").textContent = post.image_path ? "✓ art set" : "";
}
function collectPost() {
  const p = {}; NEWS_FIELDS.forEach((f) => { const el = $(`[data-n="${f}"]`); if (el) p[f] = el.value; });
  return p;
}

// ---- lineup editor --------------------------------------------------------
function buildRow(panel) {
  const row = $("#panel-row").content.cloneNode(true).querySelector(".prow");
  FIELDS.forEach((f) => { const el = row.querySelector(`[data-f="${f}"]`); if (el) el.value = panel[f] || ""; });
  if (panel.logo_path) row.querySelector(".art-state").textContent = "✓ logo";
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove(); if (!$$(".prow").length) $("#editor").classList.add("hidden");
  });
  row.querySelector(".art-file").addEventListener("change", (e) =>
    uploadFile("/upload", e.target.files[0], {}, row.querySelector(".art-state"), row.querySelector('[data-f="image_path"]'), "✓ custom art"));
  row.querySelector(".logo-file").addEventListener("change", (e) =>
    uploadFile("/upload_logo", e.target.files[0], { title: row.querySelector('[data-f="title"]').value },
      row.querySelector(".art-state"), row.querySelector('[data-f="logo_path"]'), "✓ logo"));
  row.querySelector(".find-logo").addEventListener("click", async () => {
    const title = row.querySelector('[data-f="title"]').value.trim(); if (!title) return;
    const state = row.querySelector(".art-state"); state.textContent = "searching logo…";
    try {
      const d = await postJSON("/find_logo", { title, provider: $("#provider").value });
      row.querySelector('[data-f="logo_path"]').value = d.logo_path; state.textContent = "✓ logo";
    } catch (e) { state.textContent = "no logo found"; }
  });
  return row;
}
async function uploadFile(url, file, extra, stateEl, targetEl, okMsg) {
  if (!file) return;
  stateEl.textContent = "uploading…";
  const fd = new FormData(); fd.append("file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  try {
    const r = await fetch(url, { method: "POST", body: fd });
    const d = await r.json(); if (!d.ok) throw new Error(d.error);
    targetEl.value = d.image_path || d.logo_path; stateEl.textContent = okMsg;
  } catch (e) { stateEl.textContent = "upload failed"; }
}
function addPanel(panel = { title: "" }) { $("#panels").appendChild(buildRow(panel)); }
function collectPanels() {
  return $$(".prow").map((row) => {
    const p = {}; FIELDS.forEach((f) => { const el = row.querySelector(`[data-f="${f}"]`); if (el) p[f] = el.value; });
    return p;
  }).filter((p) => p.title.trim());
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
  const payload = { style: STATE.current, runid: STATE.runid, ...options() };
  if (STATE.mode === "news") payload.post = collectPost(); else payload.panels = collectPanels();
  try { const d = await postJSON("/render", payload); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}
async function downloadZip() {
  if (!STATE.current || STATE.mode === "news") return;
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
  $("#news").placeholder = m === "news"
    ? "Paste one news story, e.g.\nAttack on Titan Final Season gets a new trailer at Anime Expo — out July 4"
    : "One announcement per line, e.g.\nAttack on Titan Season 4 new info — June 19\nJujutsu Kaisen movie — July 3";
  ["#templates", "#preview-wrap", "#editor"].forEach((s) => $(s).classList.add("hidden"));
  $("#empty").classList.remove("hidden");
}

$$('input[name=mode]').forEach((r) => r.addEventListener("change", onModeChange));
$("#generate").addEventListener("click", generate);
$("#rerender").addEventListener("click", applyEdits);
$("#add-panel").addEventListener("click", () => addPanel());
$("#dl-zip").addEventListener("click", downloadZip);
$("#news-art")?.addEventListener("change", (e) =>
  uploadFile("/upload", e.target.files[0], {}, $("#news-art-state"), $('[data-n="image_path"]'), "✓ art set"));
$("#copy-caption").addEventListener("click", () => {
  navigator.clipboard.writeText($("#caption").value);
  $("#copy-caption").textContent = "Copied!"; setTimeout(() => ($("#copy-caption").textContent = "Copy"), 1500);
});
$("#news").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate(); });
onModeChange();
