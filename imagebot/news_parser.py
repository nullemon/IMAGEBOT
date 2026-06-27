"""Turn free-text news into structured Panels.

Uses an AI provider when one is configured; otherwise a rule-based fallback so
the tool still works with no API keys.
"""
from __future__ import annotations

import re

from .models import Panel, NewsPost, RankingList, RankEntry
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


NEWS_POST_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "a punchy news sentence (sentence case, not ALL CAPS)"},
        "body": {"type": "string", "description": "optional one-line sub-text"},
        "category": {"type": "string", "description": "NEWS / BREAKING / RELEASE DATE / RANKING / TRAILER / NEW SEASON / MANGA"},
        "source": {"type": "string", "description": "a handle if present, else empty"},
        "date_text": {"type": "string", "description": "short date in CAPS, e.g. JULY 4, or empty"},
        "query": {"type": "string", "description": "best Google Images query for the key visual"},
        "items": {"type": "array", "items": {"type": "string"}, "description": "list entries if this is a ranking/list, else empty"},
    },
    "required": ["headline"],
    "additionalProperties": False,
}

_NEWS_SYSTEM = """You are an editor for an anime-news Instagram page. Turn the \
user's note into ONE news post.
- headline: a clear, punchy news sentence (sentence case, not ALL CAPS).
- category: a short label — NEWS, BREAKING, RELEASE DATE, RANKING, TRAILER, \
NEW SEASON, MANGA, etc. Infer it.
- source: a handle/source if present, else "".
- date_text: a SHORT date in CAPS like "JULY 4" if present, else "".
- query: the best Google Images search for the key visual (add "anime key visual").
- items: if it's a ranking/list, the entries in order; otherwise [].
Return JSON only."""


def parse_news_post(text: str, settings, provider=None) -> NewsPost:
    text = (text or "").strip()
    if not text:
        return NewsPost(headline="")
    prov = provider if provider is not None else get_text_provider(settings)
    if prov is not None:
        try:
            data = prov.complete_json(_NEWS_SYSTEM, f"Note:\n\n{text}", NEWS_POST_SCHEMA)
            if isinstance(data, dict) and data.get("headline"):
                return NewsPost.from_dict(data)
        except Exception:
            pass
    return _heuristic_news_post(text)


def _heuristic_news_post(text: str) -> NewsPost:
    # structured "HEADLINE: ... / CATEGORY: ... / DATE: ... / SOURCE: ... / ITEMS:"
    labels = {k.lower(): v for k, v in
              re.findall(r"(?im)^\s*(headline|category|date|source)\s*:\s*(.+?)\s*$", text)}
    if labels.get("headline"):
        items = []
        m = re.search(r"(?ims)^\s*items?\s*:\s*\n(.+)$", text)
        if m:
            for ln in m.group(1).splitlines():
                ln = ln.strip(" -*•\t").lstrip("0123456789.").strip()
                if ln:
                    items.append(ln)
        return NewsPost(
            headline=labels["headline"],
            category=(labels.get("category") or "NEWS").upper(),
            date_text=(labels.get("date") or "").upper(),
            source=labels.get("source") or "",
            items=items,
            body="\n".join(items),
            query=f"{labels['headline']} anime key visual",
        )

    lines = [l.strip(" -–—•\t") for l in text.splitlines() if l.strip()]
    headline = lines[0] if lines else text
    items = lines[1:] if len(lines) > 1 else []
    low = text.lower()
    category = "NEWS"
    for kw, cat in (("breaking", "BREAKING"), ("release date", "RELEASE DATE"),
                    ("releases", "RELEASE DATE"), ("trailer", "TRAILER"), ("pv", "TRAILER"),
                    ("top ", "RANKING"), ("ranking", "RANKING"), ("best ", "RANKING"),
                    ("manga", "MANGA"), ("new season", "NEW SEASON"), ("season", "NEW SEASON")):
        if kw in low:
            category = cat
            break
    return NewsPost(
        headline=headline,
        category=category,
        date_text=_extract_date(text),
        items=items if category == "RANKING" else [],
        body="" if category == "RANKING" else " ".join(items),
        query=f"{headline} anime key visual",
    )


def _item_lines_for_autopilot(text: str) -> list[str]:
    """The raw per-item source lines (same split the heuristic parser uses).
    Autopilot maps each parsed panel back to its line to read verb/date/leak cues."""
    chunks = re.split(r"\n\s*\n", text) if "\n\n" in text else (text or "").splitlines()
    items = []
    for c in chunks:
        for line in re.split(r"\n|;|•|\* ", c):
            line = line.strip(" -–—\t")
            if len(line) >= 2 and not re.match(r"(?i)^(title|subtitle|source|date)\s*:", line):
                items.append(line)
    return items


def _heuristic_parse(text: str, default_tag_sub: str, max_panels: int) -> list[Panel]:
    # split into items: blank-line groups, then bullets/newlines
    items = _item_lines_for_autopilot(text)
    if not items:
        items = [text]

    panels: list[Panel] = []
    for line in items[:max_panels]:
        if "|" in line:                       # structured "Title | STATUS | DATE"
            parts = [p.strip() for p in line.split("|")]
            title = parts[0] or line
            status = (parts[1].upper() if len(parts) > 1 and parts[1] else _extract_tag(line))
            date = parts[2].upper() if len(parts) > 2 and parts[2] else ""
        else:                                  # free text
            title = _clean_title(line) or line
            status = _extract_tag(line)
            date = _extract_date(line)
        panels.append(Panel(
            title=title,
            tag_main=status or default_tag_sub,
            tag_sub=default_tag_sub,
            date_text=date,
            query=f"{title} anime key visual official art",
        ))
    return panels


# ==========================================================================
# Ranking lists (Top-N, Anime-Corner style)
# ==========================================================================
RANKING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "the list title in CAPS, e.g. 'TOP 10 FEMALE CHARACTERS'"},
        "subtitle": {"type": "string", "description": "a sub-line like 'BASED ON SPRING 2026 WEEK 11 (JUN 12 - JUN 19)', else ''"},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "the character / title being ranked"},
                    "source": {"type": "string", "description": "the anime/series it is from (or a short sub-line); '' if same as name"},
                    "query": {"type": "string", "description": "best Google Images query for this character's official art"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "entries"],
    "additionalProperties": False,
}

_RANKING_SYSTEM = """You are an editor for an anime-news Instagram page that \
posts Top-N ranking graphics (like Anime Corner). Turn the user's note/list into \
one structured ranking.
- title: a short headline in CAPS, e.g. "TOP 10 FEMALE CHARACTERS". Keep the \
user's wording if given; otherwise infer it from the list.
- subtitle: a sub-line such as the poll/source/week, e.g. "BASED ON SPRING 2026 \
WEEK 11 (JUN 12 - JUN 19)" if present, else "".
- entries: in ranked order (best first). name = the character/title being ranked; \
source = the anime/series it is from (or a short sub-line), "" if there is none. \
query = the best Google Images search for that character's official art.
Return JSON only."""


def parse_ranking(text: str, settings, provider=None, max_entries: int = 20) -> RankingList:
    text = (text or "").strip()
    if not text:
        return RankingList(title="TOP 10", entries=[])
    prov = provider if provider is not None else get_text_provider(settings)
    if prov is not None:
        try:
            data = prov.complete_json(_RANKING_SYSTEM, f"Note:\n\n{text}", RANKING_SCHEMA)
            if isinstance(data, dict) and data.get("entries"):
                rl = RankingList(title=(data.get("title") or "TOP 10").upper(),
                                 subtitle=(data.get("subtitle") or "").strip())
                for i, it in enumerate(data["entries"][:max_entries], 1):
                    if isinstance(it, dict) and (it.get("name") or "").strip():
                        name = it["name"].strip()
                        src = (it.get("source") or "").strip()
                        rl.entries.append(RankEntry(
                            rank=i, name=name, source=src,
                            query=(it.get("query") or f"{name} {src} anime").strip()))
                if rl.entries:
                    return rl
        except Exception:
            pass
    return _heuristic_ranking(text, max_entries)


def _split_name_source(s: str) -> tuple[str, str]:
    s = s.strip()
    m = re.match(r"^(.+?)\s*[\(\[]([^)\]]+)[\)\]]\s*$", s)   # "Name (Show)"
    if m:
        return m.group(1).strip(), m.group(2).strip()
    for sep in (" — ", " – ", " - ", " | ", " · ", " / ", " from ", " — ", ": "):
        if sep in s:
            a, b = s.split(sep, 1)
            return a.strip(), b.strip()
    return s, ""


_RANK_PREFIX_RE = re.compile(r"^\s*#?\s*(\d{1,2})\s*[\.\)\-:–—]\s*(.+)$")


def _heuristic_ranking(text: str, max_entries: int) -> RankingList:
    labels = {k.lower(): v.strip() for k, v in
              re.findall(r"(?im)^\s*(title|subtitle|sub)\s*:\s*(.+?)\s*$", text)}
    title = (labels.get("title") or "").upper()
    subtitle = labels.get("subtitle") or labels.get("sub") or ""

    m = re.search(r"(?ims)^\s*(?:items?|entries|list|ranking)\s*:\s*\n(.+)$", text)
    body = m.group(1) if m else text

    entries: list[RankEntry] = []
    for ln in body.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if re.match(r"(?i)^(title|subtitle|sub|items?|entries|list|ranking)\s*:", ln):
            continue
        nm = _RANK_PREFIX_RE.match(ln)
        if nm:
            part = nm.group(2).strip()
        else:
            low = ln.lower()
            # an un-numbered heading like "Top 10 Female Characters" -> the title
            if not entries and not title and any(
                    k in low for k in ("top ", "best ", "ranking", "tier")):
                title = ln.upper()
                continue
            part = ln.lstrip("-*•· ").strip()
        if not part:
            continue
        name, source = _split_name_source(part)
        entries.append(RankEntry(rank=len(entries) + 1, name=name, source=source,
                                 query=f"{name} {source} anime".strip()))
        if len(entries) >= max_entries:
            break

    if not entries:
        entries = [RankEntry(rank=1, name=text[:60])]
    return RankingList(title=title or "TOP 10", subtitle=subtitle, entries=entries)
