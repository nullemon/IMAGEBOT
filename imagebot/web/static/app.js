"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const FIELDS = ["title", "subtitle", "tag_main", "tag_sub", "date_text",
  "logo_style", "theme", "query", "image_url", "image_path", "logo_path"];

let STATE = { runid: "", variants: [], selected: "" };

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

// ---- gallery --------------------------------------------------------------
function showResult(data) {
  STATE.runid = data.runid; STATE.variants = data.variants;
  $("#empty").classList.add("hidden");
  $("#run-note").textContent = `run ${data.runid} · ${data.variants.length} styles · ${data.provider_used}`;
  $("#provider-note").textContent = "provider: " + data.provider_used;

  const g = $("#gallery"); g.innerHTML = "";
  data.variants.forEach((v) => {
    const tile = document.createElement("button");
    tile.className = "tile"; tile.type = "button";
    tile.innerHTML = `<img loading="lazy" src="${bust(v.cards[0])}" alt="${v.name}"><span>${v.name}</span>`;
    tile.addEventListener("click", () => selectStyle(v.key));
    g.appendChild(tile);
  });

  const w = $("#warnings"); w.innerHTML = "";
  (data.warnings || []).forEach((x) => { const li = document.createElement("li"); li.textContent = x; w.appendChild(li); });

  if (data.caption) { $("#caption-wrap").classList.remove("hidden"); $("#caption").value = data.caption; }

  $("#panels").innerHTML = "";
  (data.panels || []).forEach(addPanel);
  $("#editor").classList.remove("hidden");

  if (data.variants[0]) selectStyle(data.variants[0].key);
}

function selectStyle(key) {
  const v = STATE.variants.find((x) => x.key === key);
  if (!v) return;
  STATE.selected = key;
  $$(".tile").forEach((t) => t.classList.toggle("active",
    t.querySelector("span").textContent === v.name));
  $("#selected").classList.remove("hidden");
  $("#sel-name").textContent = v.name;
  const sc = $("#sel-cards"); sc.innerHTML = "";
  v.cards.forEach((src, i) => {
    const div = document.createElement("div"); div.className = "sel-card";
    div.innerHTML = `<img src="${bust(src)}"><a class="dl" href="${bust(src)}" download>⬇ card ${i + 1}</a>`;
    sc.appendChild(div);
  });
  $("#selected").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function downloadZip() {
  if (!STATE.selected) return;
  setBusy(true, "Building carousel…");
  try {
    const d = await postJSON("/carousel", {
      panels: collectPanels(), runid: STATE.runid, style: STATE.selected,
      cover: $("#cover").checked, ...options(),
    });
    setBusy(false, "Carousel ready.");
    const a = document.createElement("a"); a.href = bust(d.zip); a.download = `${STATE.selected}_carousel.zip`;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { setBusy(false, "Error: " + e.message); }
}

// ---- editable panels ------------------------------------------------------
function buildRow(panel) {
  const row = $("#panel-row").content.cloneNode(true).querySelector(".prow");
  FIELDS.forEach((f) => { const el = row.querySelector(`[data-f="${f}"]`); if (el) el.value = panel[f] || ""; });
  const state = row.querySelector(".art-state");
  if (panel.logo_path) state.textContent = "✓ logo";

  row.querySelector(".remove").addEventListener("click", () => {
    row.remove(); if (!$$(".prow").length) $("#editor").classList.add("hidden");
  });
  row.querySelector(".art-file").addEventListener("change", (e) =>
    uploadFile("/upload", e.target.files[0], {}, row, "image_path", "✓ custom art"));
  row.querySelector(".logo-file").addEventListener("change", (e) =>
    uploadFile("/upload_logo", e.target.files[0],
      { title: row.querySelector('[data-f="title"]').value }, row, "logo_path", "✓ logo"));
  row.querySelector(".find-logo").addEventListener("click", async () => {
    const title = row.querySelector('[data-f="title"]').value.trim();
    if (!title) return;
    state.textContent = "searching logo…";
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
  setBusy(true, "Parsing, finding art, rendering every style… (image search can take a bit)");
  try { const d = await postJSON("/generate", { news, ...options() }); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}
async function rerender() {
  setBusy(true, "Re-rendering all styles with your edits…");
  try { const d = await postJSON("/render", { panels: collectPanels(), ...options() }); showResult(d); setBusy(false, (d.log || []).join("\n")); }
  catch (e) { setBusy(false, "Error: " + e.message); }
}

$("#generate").addEventListener("click", generate);
$("#rerender").addEventListener("click", rerender);
$("#add-panel").addEventListener("click", () => addPanel());
$("#dl-zip").addEventListener("click", downloadZip);
$("#copy-caption").addEventListener("click", () => {
  navigator.clipboard.writeText($("#caption").value);
  $("#copy-caption").textContent = "Copied!"; setTimeout(() => ($("#copy-caption").textContent = "Copy"), 1500);
});
$("#news").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate(); });
