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
                          _extract_date, _has_month_date, _item_lines_for_autopilot)
from .providers import get_text_provider

RANK_MAX = 20


# --------------------------------------------------------------------------
# event taxonomy:  pattern → (event, confirmed verb, tentative verb, tag, accent)
# Order matters — the first pattern found in the text wins, so the most
# specific phrases come first. All patterns are word-boundary-aware, so
# 'cast' never fires inside "Castle"/"broadcast", 'game' never inside
# "endgame", 'record' never inside "recorded", and "ends."/"wins!" still hit.
# --------------------------------------------------------------------------
EV = namedtuple("EV", "key verb verb_t tag accent")


def _erx(pattern: str) -> re.Pattern:
    return re.compile(r"(?<![a-z])(?:" + pattern + r")(?![a-z])")


_EVENTS: list[tuple[re.Pattern, EV]] = [(_erx(p), ev) for p, ev in [
    # --- specific multi-word phrases first (they win over the generic words) ---
    (r"final\s+season", EV("finale", "ENDING", "ENDING", "FINAL SEASON", "#ff4d5e")),
    (r"new\s+chapters?", EV("manga", "RETURNS", "RETURNING", "MANGA", "#48d08a")),
    (r"release\s+dates?", EV("release", "RELEASED", "RELEASING", "RELEASE DATE", "#48d08a")),
    (r"box\s+office", EV("box_office", "SMASHES", "SMASHING", "BOX OFFICE", "#19c37d")),
    (r"highest[\s-]gross\w*", EV("box_office", "SMASHES", "SMASHING", "BOX OFFICE", "#19c37d")),
    (r"billion\s+yen", EV("box_office", "SMASHES", "SMASHING", "BOX OFFICE", "#19c37d")),
    (r"anime\s+of\s+the\s+year", EV("award", "WINS", "WINNING", "ANIME OF THE YEAR", "#ffd23f")),
    (r"wins", EV("award", "WINS", "WINNING", "AWARD", "#ffd23f")),
    (r"awards?", EV("award", "WINS", "WINNING", "AWARD", "#ffd23f")),
    (r"voice\s+actors?", EV("casting", "CAST", "CASTING", "VOICE CAST", "#5b8cff")),
    (r"voice\s+cast", EV("casting", "CAST", "CASTING", "VOICE CAST", "#5b8cff")),
    (r"seiyuu", EV("casting", "CAST", "CASTING", "VOICE CAST", "#5b8cff")),
    (r"cast\s+as", EV("casting", "CAST", "CASTING", "CASTING", "#5b8cff")),
    (r"joins\s+the\s+cast", EV("casting", "JOINS", "JOINING", "CASTING", "#5b8cff")),
    (r"anniversar(?:y|ies)", EV("anniversary", "CELEBRATES", "CELEBRATING", "ANNIVERSARY", "#ffd23f")),
    (r"english\s+dub(?:bed)?", EV("dub", "DUBBED", "DUBBING", "ENGLISH DUB", "#3fa7ff")),
    (r"live[\s-]action", EV("live_action", "CONFIRMED", "RUMORED", "LIVE ACTION", "#b07cff")),
    (r"anime\s+adaptation", EV("adaptation", "GETS ANIME", "RUMORED", "ANIME ADAPTATION", "#f5a623")),
    (r"gets?\s+(?:an\s+)?anime", EV("adaptation", "GETS ANIME", "RUMORED", "ANIME ADAPTATION", "#f5a623")),
    (r"spin[\s-]?offs?", EV("spinoff", "ANNOUNCED", "RUMORED", "SPIN-OFF", "#5b8cff")),
    (r"sequels?", EV("sequel", "CONFIRMED", "RUMORED", "SEQUEL", "#3fa7ff")),
    (r"crossovers?", EV("collab", "REVEALED", "RUMORED", "CROSSOVER", "#ff39a8")),
    (r"most[\s-]watched", EV("record", "TOPS CHARTS", "NEARING", "RECORD", "#19c37d")),
    (r"break(?:s|ing)?\s+(?:the\s+)?records?", EV("record", "BREAKS RECORDS", "NEARING", "RECORD", "#19c37d")),
    (r"records?", EV("record", "BREAKS RECORDS", "NEARING", "RECORD", "#19c37d")),
    (r"comes?\s+back", EV("returns", "RETURNS", "RETURNING", "RETURNS", "#f5a623")),
    (r"return(?:s|ed|ing)?", EV("returns", "RETURNS", "RETURNING", "RETURNS", "#f5a623")),
    (r"resum(?:es?|ed|ing)", EV("returns", "RESUMES", "RESUMING", "RETURNS", "#f5a623")),
    (r"continu(?:es|ed|ing)", EV("returns", "CONTINUES", "CONTINUING", "RETURNS", "#f5a623")),
    (r"postpon(?:es?|ed|ing)", EV("delay", "DELAYED", "DELAYED", "DELAYED", "#ff8a3c")),
    (r"delay(?:s|ed|ing)?", EV("delay", "DELAYED", "DELAYED", "DELAYED", "#ff8a3c")),
    (r"hiatus", EV("hiatus", "ON HIATUS", "ON HIATUS", "HIATUS", "#ff8a3c")),
    (r"cancel(?:s|l?ed|ling|lation)?", EV("cancel", "CANCELLED", "CANCELLED", "CANCELLED", "#ff4d5e")),
    (r"trailers?", EV("trailer", "REVEALED", "TEASED", "NEW PV", "#5b8cff")),
    (r"teas(?:ers?|ed|ing)", EV("trailer", "TEASED", "TEASED", "NEW PV", "#5b8cff")),
    (r"pv", EV("trailer", "REVEALED", "TEASED", "NEW PV", "#5b8cff")),
    (r"key\s+visuals?", EV("visual", "REVEALED", "TEASED", "KEY VISUAL", "#5b8cff")),
    (r"premier(?:es?|ed|ing)", EV("premiere", "PREMIERES", "PREMIERING", "NEW SEASON", "#3fa7ff")),
    (r"debut(?:s|ed|ing)?", EV("premiere", "DEBUTS", "DEBUTING", "NEW SEASON", "#3fa7ff")),
    (r"air(?:s|ed|ing)", EV("premiere", "PREMIERES", "PREMIERING", "NEW SEASON", "#3fa7ff")),
    (r"movies?", EV("movie", "CONFIRMED", "RUMORED", "MOVIE", "#b07cff")),
    (r"films?", EV("movie", "CONFIRMED", "RUMORED", "MOVIE", "#b07cff")),
    (r"ovas?", EV("movie", "ANNOUNCED", "RUMORED", "OVA", "#b07cff")),
    (r"ending", EV("finale", "ENDING", "ENDING", "FINALE", "#ff4d5e")),
    (r"ends", EV("finale", "ENDS", "ENDING", "FINALE", "#ff4d5e")),
    (r"conclud(?:es|ed|ing)", EV("finale", "ENDS", "ENDING", "FINALE", "#ff4d5e")),
    (r"final\s+arc", EV("finale", "ENDING", "ENDING", "FINAL ARC", "#ff4d5e")),
    (r"seasons?", EV("new_season", "RETURNS", "RETURNING", "NEW SEASON", "#3fa7ff")),
    (r"new\s+arcs?", EV("new_season", "RETURNS", "RETURNING", "NEW ARC", "#3fa7ff")),
    (r"games?", EV("game", "ANNOUNCED", "RUMORED", "GAME", "#19c37d")),
    (r"collab(?:s|oration|orations|orating)?", EV("collab", "REVEALED", "RUMORED", "COLLAB", "#ff39a8")),
    (r"cast(?:ing)?", EV("casting", "REVEALED", "RUMORED", "CASTING", "#5b8cff")),
    (r"leak(?:s|ed|ing)?", EV("leak", "LEAKED", "LEAKED", "LEAK", "#b07cff")),
    (r"confirm(?:s|ed|ing|ation)?", EV("confirm", "CONFIRMED", "RUMORED", "CONFIRMED", "#48d08a")),
    (r"announc(?:es?|ed|ing|ements?)", EV("announce", "ANNOUNCED", "RUMORED", "NEW SERIES", "#f5a623")),
    (r"reveal(?:s|ed|ing)?", EV("announce", "REVEALED", "TEASED", "REVEALED", "#f5a623")),
    (r"ongoing", EV("ongoing", "RETURNS", "RETURNING", "ONGOING", "#f5a623")),
]]
_GENERIC = EV("news", "ANNOUNCED", "RUMORED", "NEWS", "#f5a623")
_VERBY = {"returns", "release", "premiere", "new_season", "movie", "finale", "delay",
          "hiatus", "cancel", "leak", "manga", "confirm", "announce", "trailer",
          "visual", "game", "collab", "casting", "ongoing", "box_office", "award",
          "anniversary", "dub", "live_action", "adaptation", "spinoff", "sequel", "record"}

_TENTATIVE_RX = re.compile(
    r"(?<![a-z])(?:leak(?:s|ed|ing)?|rumou?r(?:s|ed)?|reportedly|unconfirmed|"
    r"not\s+(?:yet\s+)?official|alleged(?:ly)?|supposedly|might|could|possibly|"
    r"speculat\w*|teased|hinted)(?![a-z])")


# --------------------------------------------------------------------------
def _event_of(text: str) -> tuple[EV, bool]:
    low = (text or "").lower()
    tentative = bool(_TENTATIVE_RX.search(low))
    for rx, ev in _EVENTS:
        if rx.search(low):
            return ev, tentative
    return _GENERIC, tentative


def _is_cjk(s: str) -> bool:
    for c in s or "":
        o = ord(c)
        if (0x3000 <= o <= 0x9FFF or 0xFF00 <= o <= 0xFFEF or
                0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF):   # + Hangul
            return True
    return False


def _badges(text: str, tentative: bool) -> list:
    if not tentative:
        return []
    low = (text or "").lower()
    if "leak" in low:
        return ["LEAK", "UNCONFIRMED"]
    if "rumor" in low or "rumour" in low:
        return ["RUMOR", "UNCONFIRMED"]
    return ["UNCONFIRMED"]


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


_TRAIL_RE = re.compile(
    r"(?i)[\s\-–—:,|]*\b(?:is|are|was|were|has|have|had|be|been|being|get|gets|"
    r"getting|got|will|would|to|on|in|at|for|of|and|the|a|an|its|it's|just|now|"
    r"not|yet|official|officially|finally|reportedly|soon)$")


def _strip_trailing(s: str) -> str:
    s = s.strip(" -–—:,|\t")
    prev = None
    while prev != s:                     # loop to a fixpoint: "is getting a" all goes
        prev = s
        s = _TRAIL_RE.sub("", s).strip(" -–—:,|\t")
    return s


def _title_dirty_cut(t: str):
    """Where dangling verb-dirt starts in a title ('… returns on'), or None.
    A keyword is dirt only when nothing but stopwords follow it — so it stays
    put in real titles like "New Game!" / "The Return of the Shield Hero"."""
    low = t.lower()
    best = None
    for rx, _ in _EVENTS:
        for m in rx.finditer(low):
            if m.start() <= 1:
                continue
            if not _strip_trailing(t[m.end():]):
                best = m.start() if best is None else min(best, m.start())
    return best


def _dedirt_title(t: str) -> str:
    prev = None
    while t and prev != t:
        prev = t
        cutp = _title_dirty_cut(t)
        if cutp is not None:
            t = _strip_trailing(t[:cutp])
    return t


def _clean_series(title: str, line: str) -> str:
    """The series-name pill text: the part of the line before the action verb.
    The known title is de-dirted first, then keyword hits INSIDE it are ignored,
    so "New Game!" survives while "Hunter x Hunter returns on" gets trimmed."""
    src = (line or title or "").strip()
    if not src:
        return (title or "").strip()
    tl = _dedirt_title((title or "").strip())
    low = src.lower()
    ti = low.find(tl.lower()) if tl else -1
    protected_end = (ti + len(tl)) if ti >= 0 else 0
    cut = len(src)
    for rx, _ in _EVENTS:
        for m in rx.finditer(low):
            if m.start() <= 1 or (ti >= 0 and m.start() < protected_end):
                continue                 # line starts with it / it's part of the title
            cut = min(cut, m.start())
            break
    cand = _strip_trailing(src[:cut]) if cut < len(src) else _strip_trailing(tl or src)
    return cand or tl or (title or src).strip()


def enrich_panel(panel: Panel, line: str) -> str:
    """Fill any missing verb-forward fields on a parsed panel from its source
    line. Respects values the LLM already provided (verb/subtitle/badges) and
    fills the gaps deterministically. Returns the event key (drives the style)."""
    scan = " ".join(x for x in (line, panel.verb, panel.title, panel.tag_main) if x)
    ev, tentative = _event_of(scan)
    date = _extract_date(scan)
    panel.title = _clean_series(panel.title, line)
    if not panel.verb:
        panel.verb = ev.verb_t if (tentative and ev.key not in ("leak", "delay", "hiatus", "cancel")) else ev.verb
    # verb-forward wants a status line here; a CJK subtitle is the JP title, replace it
    if not panel.subtitle or _is_cjk(panel.subtitle):
        panel.subtitle = _subtitle(ev, scan, date, tentative)
    if not panel.badges and tentative:
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
    low = line.lower()
    return any(rx.search(low) for rx, _ in _EVENTS)


# Flip to True to ALWAYS ask the AI router (every paste), even on unambiguous
# input. Default False = ask the AI on every prose/article/ambiguous paste (where
# it adds accuracy) and trust the heuristic only when the format is 100% clear.
ALWAYS_LLM_ROUTE = False


def _looks_prose(text: str) -> bool:
    """True when the text reads like an article/paragraphs (not a tidy list)."""
    t = (text or "").strip()
    lines = [l for l in t.splitlines() if l.strip()]
    if len(t) > 240 and t.count(". ") >= 2:
        return True
    if len(lines) <= 2 and len(t) > 180:
        return True
    return any(len(l) > 140 for l in lines)


def _route_confident(text: str) -> tuple[str, bool]:
    """Heuristic route + whether it's certain. Uncertain → let the AI decide."""
    t = (text or "").strip()
    if not t:
        return "news", True
    low = t.lower()
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    numbered = [l for l in lines if _NUM_LINE.match(l)]
    has_items_label = bool(re.search(r"(?im)^\s*items?\s*:", t))
    ranking_words = bool(re.search(r"(?i)\btop\s*\d+\b|\branking\b|\btier\s*list\b|\bbest\s+\w+\s+of\b|\branked\b", low))
    prose = _looks_prose(t)
    # ranking wording but no visible list → could be a ranking write-up: let the AI judge
    fuzzy_rank = ranking_words and len(numbered) < 3 and not has_items_label

    # a numbered list (or explicit ITEMS:) is an unambiguous structure
    if len(numbered) >= 3:
        if ranking_words or has_items_label:
            return "ranking", True
        # month-based dates only — a bare year like "(2023)" is common in rankings
        verby = sum(1 for l in numbered if _has_event_kw(l) or _has_month_date(l) or "|" in l)
        if verby >= max(2, (len(numbered) + 1) // 2):
            return "lineup", True
        return "ranking", True
    if ranking_words and (has_items_label or len(numbered) >= 2 or len(lines) >= 4):
        return "ranking", not prose          # "the best … of" inside an article → let AI confirm

    items = _split_items(t)
    if len(items) >= 2:
        # piped / short status lines are clearly a line-up; prose paragraphs aren't
        sure = (any("|" in l for l in items) or (not prose and all(len(i) < 120 for i in items))) and not fuzzy_rank
        return "lineup", sure
    # a single chunk: only a short, single-sentence headline is "obviously" one
    # story — anything longer / multi-sentence / ranking-ish defers to the AI.
    if prose or fuzzy_rank or t.count(". ") >= 1 or len(t) >= 120:
        return "news", False
    return "news", True


def route(text: str) -> str:
    """Return 'ranking' | 'lineup' | 'news' (heuristic only)."""
    return _route_confident(text)[0]


def _match_line(panel: Panel, lines: list, used: set):
    """Find the source line this panel came from. Scores every candidate and
    picks the best (exact word-boundary containment beats a prefix guess), so
    'Attack on Titan' no longer steals 'Attack on Titan: Junior High' lines."""
    tl = (panel.title or "").strip().lower()
    if not tl:
        return None
    rx = re.compile(r"(?<![a-z0-9])" + re.escape(tl) + r"(?![a-z0-9])")
    best_i, best_score = None, 0
    for i, ln in enumerate(lines):
        if i in used:
            continue
        low = ln.lower()
        m = rx.search(low)
        score = 0
        if m:
            score = 100
            if low[m.end():m.end() + 1] in (":", "-", "–", "—"):
                score -= 40              # likely a longer, different title
        elif len(tl) >= 8 and tl[:8] in low:
            score = 10
        if score > best_score:
            best_i, best_score = i, score
    if best_i is None:
        return None
    used.add(best_i)
    return lines[best_i]


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


def _pick_lineup_style(panels: list, event_keys: list) -> str:
    n = len(event_keys)
    if not n:
        return "spotlight"
    verby = 0
    for p, k in zip(panels, event_keys):
        v = (p.verb or "").upper()
        if k in _VERBY or (v and v not in ("", "NEWS", "ANNOUNCED")):
            verby += 1
    return "returns" if verby / n >= 0.5 else "spotlight"


def _pick_news_template(post: NewsPost, ev: EV, tentative: bool) -> str:
    cat = (post.category or "").upper()
    if tentative or ev.key in ("leak", "delay", "hiatus", "cancel") or "BREAK" in cat:
        return "breaking"
    if ev.key in ("release", "premiere") or "RELEASE" in cat:
        return "release"
    if ev.key in ("trailer", "visual") or "TRAILER" in cat:
        return "poster"
    if ev.key in ("box_office", "award", "record", "anniversary"):
        return "poster"
    if ev.key == "finale":
        return "stamp"
    if "QUOTE" in cat or "interview" in (post.headline or "").lower():
        return "quote"
    if ev.key in ("movie", "game", "casting", "live_action", "adaptation", "sequel",
                  "spinoff", "collab", "dub"):
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


_ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["ranking", "lineup", "news"]},
        "reason": {"type": "string"},
    },
    "required": ["mode"],
    "additionalProperties": False,
}

_ROUTE_SYSTEM = """You triage anime/manga news text for a graphics tool. Read it \
(it may be a full article or several paragraphs) and pick the ONE best format:
- "ranking": a Top-N / ranked list of characters, shows, or moments (even if the \
list is written as prose or numbered, or buried inside an article).
- "lineup": several SEPARATE updates about DIFFERENT series (2+), each with its own \
status — returns, release, trailer, leak, collab, award, casting, box office, etc.
- "news": a SINGLE story about one thing (one headline), even a long article.
Return JSON only."""


def _llm_route(text: str, prov) -> str | None:
    if prov is None:
        return None
    try:
        data = prov.complete_json(_ROUTE_SYSTEM, f"Text:\n\n{text}", _ROUTE_SCHEMA)
        m = data.get("mode") if isinstance(data, dict) else None
        if m in ("ranking", "lineup", "news"):
            return m
    except Exception:
        pass
    return None


def auto_design(text: str, settings, opts=None, provider=None, progress=None) -> AutoPlan:
    from .pipeline import GenerateOptions
    opts = opts or GenerateOptions()
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    # heuristic first; when it's not certain (prose, articles, ambiguous), the AI
    # reads the whole thing and decides — so accuracy is highest exactly where it
    # matters, without a wasted call on dead-obvious lists/headlines.
    mode, sure = _route_confident(text)
    if prov is not None and (ALWAYS_LLM_ROUTE or not sure):
        mode = _llm_route(text, prov) or mode
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
        # match longest titles first so "X: Junior High" claims its line before "X"
        srcs: list = [None] * len(panels)
        for i in sorted(range(len(panels)), key=lambda j: -len(panels[j].title or "")):
            srcs[i] = _match_line(panels[i], lines, used)
        keys = []
        for i, p in enumerate(panels):
            src = srcs[i] if srcs[i] is not None else (lines[i] if i < len(lines) else "")
            keys.append(enrich_panel(p, src))
        style = _pick_lineup_style(panels, keys)
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
