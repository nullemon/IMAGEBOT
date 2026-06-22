# 📋 AI research prompts

Paste one of these into **ChatGPT / Claude / Gemini / Grok**, fill in the topic,
and copy the result straight into IMAGEBOT (the matching mode). The output is in
the exact format IMAGEBOT reads — so it works even with no AI key inside the app.

The web UI has a **"AI research prompt"** box (with a Copy button) that shows the
right one for the mode you're in — these are the same prompts.

---

## Line-up list (multi-series carousel)

```
You are an anime-news researcher. Find 6 of the latest, notable anime
announcements. (Topic: leave blank for trending, or specify e.g. "Anime Expo
2026 announcements" / "summer 2026 season".)

Output ONLY a plain list — one announcement per line, no numbering, no extra
text — in this EXACT format:

Title | STATUS | DATE

Rules:
- Title: the official English series name only.
- STATUS: one of SEASON 4, MOVIE, NEW ARC, FINALE, NEW PV, NEW SERIES, GAME
  (pick the most fitting).
- DATE: a short date like "JULY 4" if there is one; otherwise omit it
  (just "Title | STATUS").

Example:
Attack on Titan | SEASON 4 | JUNE 19
Jujutsu Kaisen | MOVIE | JULY 3
Chainsaw Man | NEW ARC
```

→ Paste the result into IMAGEBOT in **Line-up list** mode.

---

## News post (single story)

```
You are an anime-news editor. Find one notable, recent anime news story.
(Topic: leave blank for trending, or specify e.g. "Attack on Titan" / "Anime
Expo 2026".)

Output ONLY these lines, nothing else:

HEADLINE: <one punchy sentence, sentence case, no ALL CAPS>
CATEGORY: <NEWS | BREAKING | RELEASE DATE | TRAILER | NEW SEASON | MANGA | RANKING>
DATE: <short date like JULY 4, or leave blank>
SOURCE: <official source or @handle if known, else leave blank>

If it's a ranking / Top-list, also add:
ITEMS:
- first item
- second item
- third item
```

→ Paste the result into IMAGEBOT in **News post** mode.

---

Tip: ask the AI for several at once — e.g. "give me 5 separate news posts in that
format, separated by a blank line" — and run them one by one.
