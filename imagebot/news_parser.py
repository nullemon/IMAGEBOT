"""Turn free-text news into structured Panels.

Uses an AI provider when one is configured; otherwise a rule-based fallback so
the tool still works with no API keys.
"""
from __future__ import annotations

import re

from .models import Panel
from .providers import get_text_provider

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_SEASON_RE = re.compile(r"\bseason\s*(\d+)\b", re.IGNORECASE)
_PART_RE = re.compile(r"\bpart\s*(\d+)\b", re.IGNORECASE)
_MONTH_ABBR = {m[:3]: m for m in _MONTHS}
_MONTH_ABBR["sept"] = "september"

PANEL_SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "subtitle": {"type": "string", "description": "original/Japanese title if well-known, else empty"},
                    "tag_main": {"type": "string", "description": "e.g. SEASON 4, MOVIE, NEW ARC, FINALE, NEW PV"},
                    "tag_sub": {"type": "string", "description": "e.g. NEW INFO, RELEASE DATE, PRE-LAUNCH"},
                    "date_text": {"type": "string", "description": "short date like 'JULY 3', or empty"},
                    "logo_style": {"type": "string", "enum": ["auto", "sans", "serif", "heavy"]},
                    "theme": {"type": "string", "description": "auto, or a colour mood: gold/navy/crimson/violet/forest/slate"},
                    "query": {"type": "string", "description": "Google Images search query for the official key visual / character art"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["panels"],
    "additionalProperties": False,
}

_SYSTEM = """You are an editor for an anime news Instagram account. You convert raw \
news notes into structured announcement panels for a graphic.

Rules:
- One panel per distinct series/title.
- title: the franchise name in English (Latin script), as it would appear as a logo.
- subtitle: the original/Japanese title ONLY if you are confident; otherwise "".
- tag_main: a short status badge in CAPS — SEASON N, MOVIE, NEW ARC, FINALE, NEW PV, \
NEW SERIES, GAME, etc. Infer from the notes.
- tag_sub: a short secondary badge — default "NEW INFO" unless the notes imply \
RELEASE DATE / TRAILER / PRE-LAUNCH etc.
- date_text: a SHORT human date in CAPS like "JULY 3" if a date is present, else "".
- logo_style: serif for elegant/period/fantasy titles, heavy for gritty/action, \
sans otherwise; "auto" if unsure.
- theme: a colour mood matching the series (gold/navy/crimson/violet/forest/slate) or "auto".
- query: the best Google Images search string to find the official key visual / \
character art for this title (include "anime key visual" or "official art").
Return JSON only."""


def parse_news(text: str, settings, provider=None, max_panels: int = 8,
               default_tag_sub: str = "NEW INFO") -> list[Panel]:
    text = (text or "").strip()
    if not text:
        return []

    prov = provider if provider is not None else get_text_provider(settings)
    if prov is not None:
        try:
            data = prov.complete_json(
                _SYSTEM,
                f"News notes:\n\n{text}\n\nReturn at most {max_panels} panels.",
                PANEL_SCHEMA,
            )
            raw = data.get("panels", data) if isinstance(data, dict) else data
            panels = []
            for item in (raw or [])[:max_panels]:
                if isinstance(item, dict) and item.get("title"):
                    p = Panel.from_dict(item)
                    if not p.tag_sub:
                        p.tag_sub = default_tag_sub
                    panels.append(p)
            if panels:
                return panels
        except Exception:
            pass  # fall through to heuristic

    return _heuristic_parse(text, default_tag_sub, max_panels)


# --------------------------------------------------------------------------
def _extract_date(s: str) -> str:
    m = _MONTH_RE.search(s)
    if not m:
        return ""
    month = _MONTH_ABBR.get(m.group(1).lower()[:3], m.group(1))
    return f"{month} {int(m.group(2))}".upper()


def _extract_tag(s: str) -> str:
    sm = _SEASON_RE.search(s)
    if sm:
        return f"SEASON {sm.group(1)}"
    pm = _PART_RE.search(s)
    if pm:
        return f"PART {pm.group(1)}"
    low = s.lower()
    for kw, tag in (("movie", "MOVIE"), ("film", "MOVIE"), ("new arc", "NEW ARC"),
                    ("final", "FINALE"), ("trailer", "NEW PV"), ("pv", "NEW PV"),
                    ("game", "GAME"), ("ova", "OVA"), ("announce", "NEW SERIES")):
        if kw in low:
            return tag
    return "NEW INFO"


# status / filler phrases to strip out of a heuristically-detected title
_NOISE_PHRASES = [
    "release date", "new arc", "new info", "new pv", "new series", "new season",
    "final season", "new trailer", "key visual", "official art", "announced",
    "confirmed", "revealed", "reveal", "trailer", "teaser", "movie", "film",
    "anime", "season", "part", "coming", "drops", "out now", "new", "info",
    "update", "ova", "game", "pv",
]
_NOISE_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in _NOISE_PHRASES) + r")\b",
                       re.IGNORECASE)


def _clean_title(s: str) -> str:
    # drop season/part/date tokens, then trailing status/filler words
    s = _SEASON_RE.sub("", s)
    s = _PART_RE.sub("", s)
    s = _MONTH_RE.sub("", s)
    s = re.sub(r"\b\d{4}\b", "", s)            # stray years
    # strip noise phrases from the END repeatedly (keep them if mid-title)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\s*[-–—:|•,]*\s*$", "", s.strip())
        s = _NOISE_RE.sub(lambda m: m.group(0) if m.start() < len(s) * 0.4 else "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" -–—:|•,\t")


def _heuristic_parse(text: str, default_tag_sub: str, max_panels: int) -> list[Panel]:
    # split into items: blank-line groups, then bullets/newlines
    chunks = re.split(r"\n\s*\n", text) if "\n\n" in text else text.splitlines()
    items = []
    for c in chunks:
        for line in re.split(r"\n|;|•|•|\* ", c):
            line = line.strip(" -–—\t")
            if len(line) >= 2:
                items.append(line)
    if not items:
        items = [text]

    panels: list[Panel] = []
    for line in items[:max_panels]:
        title = _clean_title(line) or line
        panels.append(Panel(
            title=title,
            tag_main=_extract_tag(line),
            tag_sub=default_tag_sub,
            date_text=_extract_date(line),
            query=f"{title} anime key visual official art",
        ))
    return panels
