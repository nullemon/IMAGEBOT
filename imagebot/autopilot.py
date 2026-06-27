"""Auto-design brain: paste anything → a render-ready plan.

`auto_design(text)` classifies what you pasted and returns a complete plan:
the right MODE (ranking / line-up / single news), the right TEMPLATE, and every
per-item field filled (the giant verb, the confidence badges, the status tag,
the mood accent, the image query, the date) — so the card looks right with one
click, while staying fully editable afterwards.

Design is deterministic and transparent (a keyword→event table + routing
heuristics) layered on top of the existing LLM-backed parsers, so it works with
or without an API key and you can see exactly why it chose what it chose. See
docs/AUTODESIGN.md for the full logic.
"""
from __future__ import annotations

import re
from collections import namedtuple
from dataclasses import dataclass, field

from .models import Panel, NewsPost, RankingList
from .news_parser import (parse_news, parse_news_post, parse_ranking,
                          _extract_date, _item_lines_for_autopilot)
from .providers import get_text_provider

RANK_MAX = 20


# --------------------------------------------------------------------------
# event taxonomy:  keyword → (event, confirmed verb, tentative verb, tag, accent)
# Order matters — the first keyword found in the text wins, so the most
# specific phrases come first.
# --------------------------------------------------------------------------
EV = namedtuple("EV", "key verb verb_t tag accent")

_EVENTS: list[tuple[str, EV]] = [
    ("final season", EV("finale", "ENDING", "ENDING", "FINAL SEASON", "#ff4d5e")),
    ("new chapter",  EV("manga", "RETURNS", "RETURNING", "MANGA", "#48d08a")),
    ("release date", EV("release", "RELEASED", "RELEASING", "RELEASE DATE", "#48d08a")),
    ("comes back",   EV("returns", "RETURNS", "RETURNING", "RETURNS", "#f5a623")),
    ("come back",    EV("returns", "RETURNS", "RETURNING", "RETURNS", "#f5a623")),
    ("return",       EV("returns", "RETURNS", "RETURNING", "RETURNS", "#f5a623")),
    ("resume",       EV("returns", "RESUMES", "RESUMING", "RETURNS", "#f5a623")),
    ("continues",    EV("returns", "CONTINUES", "CONTINUING", "RETURNS", "#f5a623")),
    ("postpone",     EV("delay", "DELAYED", "DELAYED", "DELAYED", "#ff8a3c")),
    ("delay",        EV("delay", "DELAYED", "DELAYED", "DELAYED", "#ff8a3c")),
    ("hiatus",       EV("hiatus", "ON HIATUS", "ON HIATUS", "HIATUS", "#ff8a3c")),
    ("cancel",       EV("cancel", "CANCELLED", "CANCELLED", "CANCELLED", "#ff4d5e")),
    ("trailer",      EV("trailer", "REVEALED", "TEASED", "NEW PV", "#5b8cff")),
    ("teaser",       EV("trailer", "TEASED", "TEASED", "NEW PV", "#5b8cff")),
    (" pv",          EV("trailer", "REVEALED", "TEASED", "NEW PV", "#5b8cff")),
    ("key visual",   EV("visual", "REVEALED", "TEASED", "KEY VISUAL", "#5b8cff")),
    ("premiere",     EV("premiere", "PREMIERES", "PREMIERING", "NEW SEASON", "#3fa7ff")),
    ("debut",        EV("premiere", "DEBUTS", "DEBUTING", "NEW SEASON", "#3fa7ff")),
    ("airs",         EV("premiere", "PREMIERES", "PREMIERING", "NEW SEASON", "#3fa7ff")),
    ("movie",        EV("movie", "CONFIRMED", "RUMORED", "MOVIE", "#b07cff")),
    ("film",         EV("movie", "CONFIRMED", "RUMORED", "MOVIE", "#b07cff")),
    (" ova",         EV("movie", "ANNOUNCED", "RUMORED", "OVA", "#b07cff")),
    ("ending",       EV("finale", "ENDING", "ENDING", "FINALE", "#ff4d5e")),
    ("ends ",        EV("finale", "ENDS", "ENDING", "FINALE", "#ff4d5e")),
    ("concludes",    EV("finale", "ENDS", "ENDING", "FINALE", "#ff4d5e")),
    ("final arc",    EV("finale", "ENDING", "ENDING", "FINAL ARC", "#ff4d5e")),
    ("season",       EV("new_season", "RETURNS", "RETURNING", "NEW SEASON", "#3fa7ff")),
    ("new arc",      EV("new_season", "RETURNS", "RETURNING", "NEW ARC", "#3fa7ff")),
    ("game",         EV("game", "ANNOUNCED", "RUMORED", "GAME", "#19c37d")),
    ("collab",       EV("collab", "REVEALED", "RUMORED", "COLLAB", "#ff39a8")),
    ("cast",         EV("casting", "REVEALED", "RUMORED", "CASTING", "#5b8cff")),
    ("leak",         EV("leak", "LEAKED", "LEAKED", "LEAK", "#b07cff")),
    ("confirm",      EV("confirm", "CONFIRMED", "RUMORED", "CONFIRMED", "#48d08a")),
    ("announce",     EV("announce", "ANNOUNCED", "RUMORED", "NEW SERIES", "#f5a623")),
    ("reveal",       EV("announce", "REVEALED", "TEASED", "REVEALED", "#f5a623")),
    ("ongoing",      EV("ongoing", "RETURNS", "RETURNING", "ONGOING", "#f5a623")),
]
_GENERIC = EV("news", "ANNOUNCED", "RUMORED", "NEWS", "#f5a623")
_VERBY = {"returns", "release", "premiere", "new_season", "movie", "finale", "delay",
          "hiatus", "cancel", "leak", "manga", "confirm", "announce", "trailer",
          "visual", "game", "collab", "casting", "ongoing"}

_TENTATIVE = ("leak", "rumor", "rumour", "reportedly", "unconfirmed", "not yet official",
              "not official", "alleged", "supposedly", "might ", "could ", "possibly",
              "speculat", "teased", "hinted")


# --------------------------------------------------------------------------
def _event_of(text: str) -> tuple[EV, bool]:
    low = " " + (text or "").lower() + " "
    tentative = any(m in low for m in _TENTATIVE)
    for kw, ev in _EVENTS:
        if kw in low:
            return ev, tentative
    return _GENERIC, tentative


def _badges(text: str, tentative: bool) -> list:
    if not tentative:
        return []
    low = text.lower()
    first = "RUMOR" if ("rumor" in low or "rumour" in low) else "LEAK"
    return [first, "UNCONFIRMED"]


def _subtitle(ev: EV, text: str, date: str, tentative: bool) -> str:
    low = text.lower()
    if "ongoing" in low or "new chapter" in low:
        return "New Chapters Ongoing"
    if ev.key == "delay":
        return f"Delayed to {date.title()}" if date else "Delayed"
    if ev.key == "hiatus":
        return "On Hiatus"
    if ev.key == "cancel":
        return "Cancelled"
    if date:
        pre = {"release": "Out", "premiere": "Premieres", "movie": "Coming",
               "trailer": "Out Now", "manga": "Out"}.get(ev.key, "On")
        return f"{pre} {date.title()}"
    if tentative:
        return "Not Yet Official"
    return ev.tag.title()


def _clean_series(title: str, line: str) -> str:
    """The series-name pill text = the bit of the line before the action verb."""
    src = line or title
    low = src.lower()
    cut = len(src)
    for kw, _ in _EVENTS:
        i = low.find(kw)
        if i > 1:
            cut = min(cut, i)
    cand = src[:cut] if cut < len(src) else (title or src)
    cand = re.sub(r"(?i)\s+(is|are|has|have|had|gets?|to|on|will|now|just|the|a|an|in|for|of|and|—|-|:|\|)\s*$",
                  "", cand.strip(" -–—:,|"))
    return cand.strip(" -–—:,|") or (title or src).strip()


def enrich_panel(panel: Panel, line: str) -> str:
    """Fill the verb-forward fields on a parsed panel from its source line.
    Returns the event key (used to decide the lineup style)."""
    scan = " ".join(x for x in (line, panel.title, panel.tag_main) if x)
    ev, tentative = _event_of(scan)
    verb = ev.verb_t if (tentative and ev.key not in ("leak", "delay", "hiatus", "cancel")) else ev.verb
    date = _extract_date(scan)
    panel.title = _clean_series(panel.title, line)
    panel.verb = verb
    panel.subtitle = _subtitle(ev, scan, date, tentative)
    panel.badges = _badges(scan, tentative)
    if ev.tag and (not panel.tag_main or panel.tag_main in ("NEW INFO", "SEASON 1")):
        panel.tag_main = ev.tag
    if not panel.accent:
        # unconfirmed news reads as violet (signals "leak"), unless it's an
        # event that already owns a warning colour (delay/hiatus/cancel/finale).
        accent = ev.accent
        if tentative and ev.key not in ("delay", "hiatus", "cancel", "finale"):
            accent = "#b07cff"
        panel.accent = accent
    if date and not panel.date_text:
        panel.date_text = date
    return ev.key


# --------------------------------------------------------------------------
# routing:  text → mode
# --------------------------------------------------------------------------
_NUM_LINE = re.compile(r"^\s*#?\s*\d{1,2}\s*[\.\)]\s+\S")


def _has_event_kw(line: str) -> bool:
    low = " " + line.lower() + " "
    return any(kw in low for kw in (k for k, _ in _EVENTS))


def route(text: str) -> str:
    """Return 'ranking' | 'lineup' | 'news'."""
    t = (text or "").strip()
    if not t:
        return "news"
    low = t.lower()
    lines = [l.strip() for l in t.splitlines() if l.strip()]

    numbered = [l for l in lines if _NUM_LINE.match(l)]
    has_items_label = bool(re.search(r"(?im)^\s*items?\s*:", t))
    ranking_words = bool(re.search(r"(?i)\btop\s*\d+\b|\branking\b|\btier\s*list\b|\bbest\s+\w+\s+of\b|\branked\b", low))

    # a numbered list: ranking unless the entries read like dated/status announcements
    if len(numbered) >= 3:
        if ranking_words or has_items_label:      # an explicit "TOP N"/"ITEMS:" wins
            return "ranking"
        verby = sum(1 for l in numbered if _has_event_kw(l) or _extract_date(l) or "|" in l)
        if verby >= max(2, (len(numbered) + 1) // 2):
            return "lineup"
        return "ranking"
    if ranking_words and (has_items_label or len(numbered) >= 2 or len(lines) >= 4):
        return "ranking"

    # not a ranking → line-up if there are clearly several separate items
    items = _split_items(t)
    if len(items) >= 2:
        return "lineup"
    return "news"


def _match_line(panel: Panel, lines: list, used: set):
    """Find the source line this panel came from (title is a substring of it)."""
    title = (panel.title or "").strip().lower()
    if title:
        for i, ln in enumerate(lines):
            if i in used:
                continue
            low = ln.lower()
            if title in low or (len(title) > 4 and title[: max(4, len(title) // 2)] in low):
                used.add(i)
                return ln
    return None


def _split_items(text: str) -> list:
    if "\n\n" in text:
        chunks = re.split(r"\n\s*\n", text)
    else:
        chunks = text.splitlines()
    out = []
    for c in chunks:
        c = c.strip(" -–—•\t")
        if len(c) >= 2 and not re.match(r"(?i)^(title|subtitle|sub|items?|source|date)\s*:", c):
            out.append(c)
    return out


def _pick_lineup_style(event_keys: list) -> str:
    n = len(event_keys)
    if not n:
        return "spotlight"
    verby = sum(1 for k in event_keys if k in _VERBY)
    return "returns" if verby / n >= 0.5 else "spotlight"


def _pick_news_template(post: NewsPost, ev: EV, tentative: bool) -> str:
    cat = (post.category or "").upper()
    if tentative or ev.key in ("leak", "delay", "hiatus", "cancel") or "BREAK" in cat:
        return "breaking"
    if ev.key in ("release", "premiere") or "RELEASE" in cat:
        return "release"
    if ev.key == "trailer" or "TRAILER" in cat:
        return "poster"
    if ev.key == "finale":
        return "stamp"
    if "QUOTE" in cat or "interview" in (post.headline or "").lower():
        return "quote"
    if ev.key in ("movie", "game"):
        return "topbar"
    return "bottom"


def _pick_rank_template(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("villain", "evil", "darkest", "death", "horror", "demon", "scariest")):
        return "dark"
    if any(k in low for k in ("neon", "cyber", "aesthetic")):
        return "neon"
    return "corner"


# --------------------------------------------------------------------------
@dataclass
class AutoPlan:
    mode: str                       # lineup | news | ranking
    template: str                   # style key (lineup) or template key (news/ranking)
    size: str = "portrait"
    panels: list = field(default_factory=list)   # for lineup
    post: object = None             # NewsPost, for news
    ranking: object = None          # RankingList, for ranking
    why: str = ""
    provider_used: str = "none"


def auto_design(text: str, settings, opts=None, provider=None, progress=None) -> AutoPlan:
    from .pipeline import GenerateOptions
    opts = opts or GenerateOptions()
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    mode = route(text)
    if progress:
        progress(f"auto-design: read this as a {mode} post (provider: {pu})")

    if mode == "ranking":
        rl = parse_ranking(text, settings, provider=prov, max_entries=RANK_MAX)
        tmpl = _pick_rank_template(text)
        why = f"Top-{len(rl.entries)} list → ranking card, “{tmpl}” style"
        return AutoPlan(mode="ranking", template=tmpl, size="portrait", ranking=rl,
                        why=why, provider_used=pu)

    if mode == "lineup":
        panels = parse_news(text, settings, provider=prov, max_panels=opts.max_panels,
                            default_tag_sub=settings.brand.default_tag_sub)
        lines = _item_lines_for_autopilot(text)
        used = set()
        keys = []
        for i, p in enumerate(panels):
            src = _match_line(p, lines, used)
            if src is None:
                src = lines[i] if i < len(lines) else ""
            keys.append(enrich_panel(p, (src + " " + p.title).strip()))
        style = _pick_lineup_style(keys)
        verbs = ", ".join(dict.fromkeys(p.verb for p in panels if p.verb)) or "updates"
        look = "verb-forward" if style == "returns" else "art-forward"
        why = f"{len(panels)} status updates ({verbs}) → line-up, {look} “{style}”"
        return AutoPlan(mode="lineup", template=style, size="portrait", panels=panels,
                        why=why, provider_used=pu)

    # single story
    post = parse_news_post(text, settings, provider=prov)
    ev, tentative = _event_of(text)
    tmpl = _pick_news_template(post, ev, tentative)
    if tentative and post.category and post.category.upper() in ("", "NEWS"):
        post.category = "LEAK"
    why = f"single story ({(post.category or 'news').lower()}) → news post, “{tmpl}” template"
    return AutoPlan(mode="news", template=tmpl, size="portrait", post=post,
                    why=why, provider_used=pu)
