# IMAGEBOT — anime news card maker

Paste a line of news → get a **gallery of ~20 finished, ready-to-post styles** to
pick from, in the “ANIME EXPO” line-up look: stacked panels with the series art,
a logo, status pills (`SEASON 4` · `NEW INFO`), the event wordmark, and a big
date — plus an auto-written caption and one-click **carousel export**.

Runs **locally**. On an Ubuntu box with a GPU it also does background cut-outs,
AI upscaling, OCR watermark clean-up, and local Stable-Diffusion art.

![card](samples/preview_classic.png)

*(Generated locally with mock key visuals. On your machine each panel uses the
real series art — AI-vision-picked, cleaned, and cut out on the GPU.)*

### Pick from a gallery of styles
Every generate renders the same news in 20 curated looks — each with its own *layout* (where the title, date, pills and art sit), not just a recolour — click the one you want:

![style gallery](samples/preview_gallery.png)

---

## What it does

```
your news text
   │  ▶ parse into panels (title, season, date…)     ← Claude / ChatGPT / Gemini / Grok, or built-in rules
   │  ▶ find each series' art on Google / DuckDuckGo  ← AI picks the cleanest; or upload / paste a URL
   │  ▶ (GPU, optional) cut-out · upscale · de-watermark
   │  ▶ render the same panels in 20 styles           ← you pick the look
   ▼
ready-to-post PNGs (1080×1350) · caption · carousel .zip (with cover slide)
```

- **20 curated styles, generated at once** — Classic Expo, Cutout Spotlight, Soft
  Focus, Duotone, Neon Night, Noir, Magazine, Cinematic Bars, Vaporwave, Minimal
  Mono, Comic Pop, Sunset, Midnight, Poster Center, Grunge, Festival, Editorial,
  Headline, Sticker, Split. Each uses one of 7 layouts (classic, centered,
  mirrored, side-panel, bottom-bar, lower-third, date-sticker). Pick one and
  download, or export the whole carousel.
- **Clean art, not clutter** — AI vision picks the best/cleanest key visual among
  candidates; the GPU stack can cut the character out onto a designed background,
  upscale low-res art, and OCR-detect + inpaint existing watermarks/text.
- **Official logos** — upload a transparent PNG per series (saved to a local
  library and reused), or auto search→download→save. Overlaid instead of text.
- **Multiple AI providers** — Claude, ChatGPT, Gemini, Grok. Use one or all; with
  **no** key it still works (rule-based parser + keyless search).
- **Carousel export** — a cover slide + the line-up cards, zipped, 1080×1350.

---

## Quickstart

```bash
git clone <your-repo-url> IMAGEBOT && cd IMAGEBOT
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # optional: add the keys you have
python run.py                   # opens http://127.0.0.1:5000
```

Paste news → **Generate** → click a style → **Download** (or the carousel `.zip`).
Need it perfect? Edit any field, upload art/logo per series, **Re-render all styles**.

### Local GPU box (Ubuntu + NVIDIA) — the full power

```bash
bash scripts/setup_local.sh     # venv + CUDA torch + cutout/detect/inpaint/upscale + models
```

Same proven stack as `nullemon/mangatranslator`, so it installs identically:

| Feature | Library | What it does |
|---|---|---|
| Cutout | `rembg` (isnet-anime) | character on a clean designed bg (the “Spotlight”/“Soft Focus” styles) |
| Text/watermark detect | comic-text-detector (ONNX) + CRAFT | pixel-level text-stroke masks |
| Erase | LaMa (`simple-lama-inpainting`) | surgically inpaint the detected text/watermarks |
| Upscale | Real-ESRGAN anime (via `spandrel`) | rescue low-res scraped art |
| (optional) | `manga-ocr` | read Japanese text |

Model weights auto-download to `models/` on first use (`comictextdetector.pt.onnx`,
Real-ESRGAN anime). **Already ran the manga translator?** Point IMAGEBOT at the
weights it downloaded to skip re-downloading:

```bash
export TEXT_SEG_MODEL=/path/to/mangatranslator/models/comictextdetector.pt.onnx
```

Everything auto-detects: if a lib/model/GPU isn't present the feature is skipped.
The web header shows how many GPU features are live; tick **“Clean watermarks”** in
the UI or pass `--clean` on the CLI to erase source text/watermarks from scraped art.

**Local Stable Diffusion art:** run AUTOMATIC1111/Forge/ComfyUI, set
`IMAGEBOT_SD_URL=http://127.0.0.1:7860` in `.env`, and the bot will GPU-generate
art (used as the AI-art fallback, no API cost).

---

## API keys (`.env`) — all optional

| Variable | Unlocks |
|---|---|
| `ANTHROPIC_API_KEY` | Claude — parsing, captions, **vision image-pick** |
| `OPENAI_API_KEY` | ChatGPT — parsing, captions, vision-pick, DALL·E art |
| `GEMINI_API_KEY` | Gemini — parsing, captions, vision-pick, Imagen art |
| `XAI_API_KEY` | Grok — parsing, captions, Aurora art |
| `SERPAPI_KEY` **or** `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | **reliable** Google image search (recommended) |
| `IMAGEBOT_SD_URL` | local Stable Diffusion server for GPU art |

The keyless DuckDuckGo/Bing search works but can rate-limit — add a SerpApi or
Google Programmable Search key for dependable, high-quality art. Order tried:
SerpApi → Google CSE → DuckDuckGo → Bing.

---

## Command line

```bash
# render all 20 styles + a caption
python -m imagebot make --news "Bleach S4 July 4
Frieren S3 July 4
Solo Leveling S3 July 4" --all-styles

# one style + carousel zip, AI picks images, GPU watermark clean-up, auto logos
python -m imagebot make --file news.txt --style noir --carousel --clean --find-logo

# fast preview, no search
python -m imagebot make --news "..." --no-art --style classic

python -m imagebot web --port 8080     # launch the UI
```

`--help` lists every flag (`--per`, `--event`, `--watermark`, `--date`,
`--ai-art`, `--no-vision`, `--cover-title`, …).

---

## How the pieces fit

```
imagebot/
  styles.py         20 curated Style presets (+ 7 distinct layouts) (the gallery you pick from)
  compositor.py     Pillow engine — backgrounds, scrims, effects, logos, dates, cover
  enhance.py        OPTIONAL GPU: rembg cutout · Real-ESRGAN upscale · OCR · LaMa inpaint
  logos.py          local logo library + upload + auto search/download
  news_parser.py    news text -> structured Panels (LLM, rule-based fallback)
  image_search.py   SerpApi/CSE/DuckDuckGo/Bing + download, score, vision-pick, cache
  pipeline.py       orchestration: parse -> art/logos -> 20 styles -> carousel
  providers/        Claude · OpenAI · Gemini · Grok · local Stable Diffusion (lazy)
  web/              Flask app + single-page gallery UI
run.py · scripts/setup_local.sh · scripts/fetch_fonts.py
```

---

## Notes & limitations

- **You are responsible for the rights** to any image/logo you search, download,
  or repost. Treat scraped art as a mock-up; publish with licensed/official art.
- Without the GPU stack, “Cutout Spotlight” / “Soft Focus” gracefully fall back to
  a treated full-bleed background (still distinct, just not a true cut-out).
- Japanese/CJK subtitles need a CJK font — `python scripts/fetch_fonts.py` (or a
  system one). Without it, subtitles are skipped rather than shown as boxes.
- Logos are overlaid as-is; titles you don't supply a logo for render as styled
  text (sans/serif/heavy).
