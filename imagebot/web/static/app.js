"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const PANEL_FIELDS = ["title", "subtitle", "tag_main", "tag_sub", "date_text",
  "logo_style", "theme", "query", "image_url", "image_path"];

function options() {
  return {
    provider: $("#provider").value,
    panels_per_card: $("#panels_per_card").value,
    event_name: $("#event_name").value,
    watermark: $("#watermark").value,
    date_text: $("#date_text").value,
    find_art: $("#find_art").checked,
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

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok || !data.ok) throw new Error(data.error || "Request failed");
  return data;
}

// ---- panel editor rows ----------------------------------------------------
function buildPanelRow(panel) {
  const tpl = $("#panel-row").content.cloneNode(true);
  const row = tpl.querySelector(".prow");
  PANEL_FIELDS.forEach((f) => {
    const el = row.querySelector(`[data-f="${f}"]`);
    if (el) el.value = panel[f] || "";
  });
  if (panel.image_path) row.querySelector(".art-state").textContent = "✓ custom art";

  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    if (!$$(".prow").length) $("#editor").classList.add("hidden");
  });

  row.querySelector(".art-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const st = row.querySelector(".art-state");
    st.textContent = "uploading…";
    try {
      const r = await fetch("/upload", { method: "POST", body: fd });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error);
      row.querySelector('[data-f="image_path"]').value = d.image_path;
      row.querySelector('[data-f="image_url"]').value = "";
      st.textContent = "✓ custom art";
    } catch (err) { st.textContent = "upload failed"; }
  });
  return row;
}

function collectPanels() {
  return $$(".prow").map((row) => {
    const p = {};
    PANEL_FIELDS.forEach((f) => {
      const el = row.querySelector(`[data-f="${f}"]`);
      if (el) p[f] = el.value;
    });
    return p;
  }).filter((p) => p.title.trim());
}

function addPanel(panel = { title: "" }) {
  $("#panels").appendChild(buildPanelRow(panel));
  $("#editor").classList.remove("hidden");
}

// ---- render results -------------------------------------------------------
function showResult(data) {
  $("#empty").classList.add("hidden");
  $("#provider-note").textContent = "provider: " + data.provider_used;

  const cards = $("#cards"); cards.innerHTML = "";
  if (data.warnings && data.warnings.length) {
    const ul = document.createElement("ul"); ul.className = "warnings";
    data.warnings.forEach((w) => { const li = document.createElement("li"); li.textContent = w; ul.appendChild(li); });
    cards.appendChild(ul);
  }
  (data.cards || []).forEach((src, i) => {
    const div = document.createElement("div"); div.className = "card-item";
    const bust = src + (src.includes("?") ? "&" : "?") + "t=" + Date.now();
    div.innerHTML = `<img src="${bust}" alt="card ${i + 1}" />
      <a class="dl" href="${bust}" download>⬇ Download card ${i + 1}</a>`;
    cards.appendChild(div);
  });

  if (data.caption) {
    $("#caption-wrap").classList.remove("hidden");
    $("#caption").value = data.caption;
  }

  // (re)build editor
  $("#panels").innerHTML = "";
  (data.panels || []).forEach((p) => addPanel(p));
}

// ---- actions --------------------------------------------------------------
async function generate() {
  const news = $("#news").value.trim();
  if (!news) { setBusy(false, "Paste some news first."); return; }
  setBusy(true, "Parsing news, finding art, compositing… (image search can take a bit)");
  try {
    const data = await postJSON("/generate", { news, ...options() });
    showResult(data);
    setBusy(false, (data.log || []).join("\n"));
  } catch (e) { setBusy(false, "Error: " + e.message); }
}

async function rerender() {
  setBusy(true, "Re-rendering with your edits…");
  try {
    const data = await postJSON("/render", { panels: collectPanels(), ...options() });
    showResult(data);
    setBusy(false, (data.log || []).join("\n"));
  } catch (e) { setBusy(false, "Error: " + e.message); }
}

// ---- wire up --------------------------------------------------------------
$("#generate").addEventListener("click", generate);
$("#rerender").addEventListener("click", rerender);
$("#add-panel").addEventListener("click", () => addPanel());
$("#copy-caption").addEventListener("click", () => {
  navigator.clipboard.writeText($("#caption").value);
  $("#copy-caption").textContent = "Copied!";
  setTimeout(() => ($("#copy-caption").textContent = "Copy"), 1500);
});
$("#news").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate();
});
