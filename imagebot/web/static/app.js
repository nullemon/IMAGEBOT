"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const FIELDS = ["title", "subtitle", "tag_main", "tag_sub", "date_text",
  "logo_style", "theme", "query", "image_url", "image_path", "logo_path"];

let STATE = { runid: "", styles: [], current: "", lastCards: [] };

function options() {
  return {
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
    c.className = "chip"; c.type = "button"; c.dataset.key = st.key;
    c.textContent = st.name;
    c.classList.toggle("active", st.key === STATE.current);
    c.addEventListener("click", () => switchTemplate(st.key));
    box.appendChild(c);
  });
}
function markActive() {
  $$("#templates .chip").forEach((c) => c.classList.toggle("active", c.dataset.key === STATE.current));
}

async function switchTemplate(key) {
  STATE.current = key; markActive();
  const pc = $("#preview-cards");
  pc.style.opacity = "0.45";
  try {
    const d = await postJSON("/render_one", {
      panels: collectPanels(), runid: STATE.runid, style: key, ...options(),
    });
    showCurrent(d);
  } catch (e) { setBusy(false, "Error: " + e.message); }
  pc.style.opacity = "1";
}

function showCurrent(d) {
  STATE.current = d.key; STATE.lastCards = d.cards; if (d.runid) STATE.runid = d.runid;
  $("#preview-wrap").classList.remove("hidden");
  $("#cur-name").textContent = d.name;
  const pc = $("#preview-cards"); pc.innerHTML = "";
  d.cards.forEach((src, i) => {
    const div = document.createElement("div"); div.className = "sel-card";
    div.innerHTML = `<img src="${bust(src)}"><a class="dl" href="${bust(src)}" download="${d.key}_${i + 1}.png">⬇ download card ${i + 1}</a>`;
    pc.appendChild(div);
  });
  markActive();
}

// ---- result wiring --------------------------------------------------------
function showResult(data) {
  STATE.runid = data.runid; STATE.styles = data.styles; STATE.current = data.current ? data.current.key : "";
  $("#empty").classList.add("hidden");
  $("#run-note").textContent = `run ${data.runid} · ${data.styles.length} templates · ${data.provider_used}`;
  $("#provider-note").textContent = "provider: " + data.provider_used;
  buildChips();

  const w = $("#warnings"); w.innerHTML = "";
  (data.warnings || []).forEach((x) => { const li = document.createElement("li"); li.textContent = x; w.appendChild(li); });
  if (data.caption) { $("#caption-wrap").classList.remove("hidden"); $("#caption").value = data.caption; }
  if (data.current) showCurrent(data.current);

  $("#panels").innerHTML = "";
  (data.panels || []).forEach(addPanel);
  $("#editor").classList.remove("hidden");
}

// ---- editable panels ------------------------------------------------------
function buildRow(panel) {
  const row = $("#panel-row").content.cloneNode(true).querySelector(".prow");
  FIELDS.forEach((f) => { const el = row.querySelector(`[data-f="${f}"]`); if (el) el.value = panel[f] || ""; });
  if (panel.logo_path) row.querySelector(".art-state").textContent = "✓ logo";
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove(); if (!$$(".prow").length) $("#editor").classList.add("hidden");
  });
  row.querySelector(".art-file").addEventListener("change", (e) =>
    uploadFile("/upload", e.target.files[0], {}, row, "image_path", "✓ custom art"));
  row.querySelector(".logo-file").addEventListener("change", (e) =>
    uploadFile("/upload_logo", e.target.files[0],
      { title: row.querySelector('[data-f="title"]').value }, row, "logo_path", "✓ logo"));
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
async function uploadFile(url, file, extra, row, field, okMsg) {
  if (!file) return;
  const state = row.querySelector(".art-state"); state.textContent = "uploading…";
  const fd = new FormData(); fd.append("file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  try {
    const r = await fetch(url, { method: "POST", body: fd });
    const d = await r.json(); if (!d.ok) throw new Error(d.error);
    row.querySelector(`[data-f="${field}"]`).value = d.image_path || d.logo_path;
    state.textContent = okMsg;
  } catch (e) { state.textContent = "upload failed"; }
}
function addPanel(panel = { title: "" }) { $("#panels").appendChild(buildRow(panel)); $("#editor").classList.remove("hidden"); }
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
  try { const d = await postJSON("/render", { panels: collectPanels(), style: STATE.current, ...options() }); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}
async function downloadZip() {
  if (!STATE.current) return;
  setBusy(true, "Building carousel…");
  try {
    const d = await postJSON("/carousel", { panels: collectPanels(), runid: STATE.runid, style: STATE.current, cover: $("#cover").checked, ...options() });
    setBusy(false, "Carousel ready.");
    const a = document.createElement("a"); a.href = bust(d.zip); a.download = `${STATE.current}_carousel.zip`;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { setBusy(false, "Error: " + e.message); }
}

$("#generate").addEventListener("click", generate);
$("#rerender").addEventListener("click", applyEdits);
$("#add-panel").addEventListener("click", () => addPanel());
$("#dl-zip").addEventListener("click", downloadZip);
$("#copy-caption").addEventListener("click", () => {
  navigator.clipboard.writeText($("#caption").value);
  $("#copy-caption").textContent = "Copied!"; setTimeout(() => ($("#copy-caption").textContent = "Copy"), 1500);
});
$("#news").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate(); });
