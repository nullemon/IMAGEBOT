# 🧠 Auto-Design logic

**Paste anything → the right card.** `✨ Auto` mode reads what you pasted, decides
the post *type*, picks the *template*, and fills every per-item field (the giant
verb, confidence badges, status tag, mood colour, image query, date) so it looks
right with one click — and you can still override everything afterwards.

It's deterministic and transparent: a keyword→event table + routing heuristics
layered on the existing LLM-backed parsers. It works **with or without** an API
key, and every choice is explained back to you ("✨ Auto-picked: …").

Code: [`imagebot/autopilot.py`](../imagebot/autopilot.py).

```
pasted text  (a line, a few updates, a Top-N list, OR a full article)
  │  1. ROUTE      → which mode?   ranking | line-up | single-news
  │                  (an AI reads the whole thing — great for articles — heuristics back it up)
  │  2. PARSE      → structure it  (LLM extracts facts incl. verb + confidence; rule-based fallback)
  │  3. ENRICH     → fill gaps: event → verb, subtitle, badges, tag, accent, date, query
  │  4. DECIDE     → exact template/style + size
  ▼
render-ready plan  →  normal render path  →  fully editable result
```

**Paste an article and it figures out the list.** The heuristic routes first and
reports whether it's *certain*. When it isn't — prose, a full article, anything
ambiguous or ranking-ish — the **AI router reads the whole thing and decides**, and
step 2's parsers pull the structure straight out of the prose (a ranking article →
the ranked entries; a roundup → the line-up; a single story → one post). On a clean
numbered list or a short headline the heuristic is already 100% sure, so it skips
that extra call (same answer, faster). The AI also fills the hero **verb** and
**confidence** per item; the deterministic engine fills whatever it leaves blank, so
it's complete and polished either way. Set `autopilot.ALWAYS_LLM_ROUTE = True` to
ask the AI on *every* paste; with no key, the rule-based router handles lines/lists.

---

## 1 · Routing (text → mode)

Evaluated in order; first match wins (`autopilot.route`):

1. **Ranking** if the text is a numbered list (`1. 2. 3.` …, ≥3 rows) whose rows
   read like *names* (no action verb / date / `|`), **or** it contains
   `TOP N` / `ranking` / `tier list` / `best … of` with a list / `ITEMS:` block.
2. **Line-up** if a numbered list's rows mostly carry a verb/date (announcements,
   not a ranking), **or** there are ≥2 separate items (blank-line groups, or
   multiple lines, or `Series | STATUS | DATE`).
3. **Single news** otherwise (one story / one headline).

Ambiguity is resolved toward the safe default (a single news post never errors).

---

## 2 · Event taxonomy

Each item is matched against a keyword table (`_EVENTS`) → an **event type**, the
**hero verb** (confirmed + tentative form), a **status tag**, and a **mood accent**:

| event | verb (confirmed / tentative) | tag | accent |
|---|---|---|---|
| returns | RETURNS / RETURNING | RETURNS | gold |
| release | RELEASED / RELEASING | RELEASE DATE | green |
| premiere / new season | PREMIERES / RETURNS | NEW SEASON | blue |
| trailer / visual | REVEALED / TEASED | NEW PV | blue |
| movie / OVA | CONFIRMED / RUMORED | MOVIE | violet |
| finale | ENDING / ENDS | FINAL SEASON | crimson |
| delay | DELAYED | DELAYED | orange |
| hiatus | ON HIATUS | HIATUS | orange |
| cancel | CANCELLED | CANCELLED | crimson |
| leak | LEAKED | LEAK | violet |
| manga chapter | RETURNS | MANGA | green |
| game / collab / crossover | ANNOUNCED / REVEALED | GAME / COLLAB | pink |
| casting / voice actor | CAST / JOINS | VOICE CAST | blue |
| box office | SMASHES | BOX OFFICE | green |
| award / anime of the year | WINS | AWARD | gold |
| record / most-watched | BREAKS RECORDS | RECORD | green |
| anniversary | CELEBRATES | ANNIVERSARY | gold |
| live action | CONFIRMED | LIVE ACTION | violet |
| anime adaptation | GETS ANIME | ANIME ADAPTATION | gold |
| sequel / spin-off | CONFIRMED / ANNOUNCED | SEQUEL / SPIN-OFF | blue |
| english dub | DUBBED | ENGLISH DUB | blue |
| (anything else) | ANNOUNCED | NEWS | gold |

The hero **verb** and **confidence** can also come straight from the AI parser
(richer phrasing on a pasted article); the table fills anything it leaves blank.

**Confidence.** Markers like *leak, rumor, reportedly, unconfirmed, not yet
official, allegedly, might/could* flip the item to **tentative** → the verb uses
the `-ING` form (RETURNING) and a **badge row** is added: `LEAK` (or `RUMOR`) +
`UNCONFIRMED`. Official news shows no badges and the present-tense verb.

**Subtitle** is composed from the event + date:
`On June 28` · `Out July 4` · `Premieres July 4` · `Coming 2027` ·
`Delayed to 2027` · `New Chapters Ongoing` · `Not Yet Official`.

The **series pill** is the clean series name (the text before the verb), so
`Hunter x Hunter returns on June 28` → pill **Hunter x Hunter**, verb **RETURNS**,
subtitle **On June 28**.

---

## 3 · Decision table (type → template + size)

| input | mode | template | why |
|---|---|---|---|
| Top-N list | `ranking` | `corner` (`dark` for villains/horror, `neon` for cyber) | the leaderboard look |
| ≥2 items, mostly status verbs | `lineup` | **`returns`** (verb-forward) | the giant-VERB stack |
| ≥2 items, generic announcements | `lineup` | `spotlight` | art-forward |
| single · leak/rumor/delay/hiatus/cancel | `news` | `breaking` | red alert bar |
| single · release/premiere | `news` | `release` | big date |
| single · trailer | `news` | `poster` | full-bleed hype |
| single · finale | `news` | `stamp` | date medallion |
| single · movie/game | `news` | `topbar` | title block |
| single · quote/interview | `news` | `quote` | pull-quote |
| single · anything else | `news` | `bottom` | clean headline |

Size defaults to **portrait 4:5**; whatever size you pick in the UI is honoured.
After the pick you get the **full** template gallery for that mode as chips, so a
swap is one click — Auto only chooses the *starting* template.

---

## 4 · The verb-forward "RETURNS" layout

Added as `layout="verbforward"` (styles **Returns**, **Returns Gold**, **Leak**).
Reproduces the reference: a giant action verb is the hero. Boxes are fractions of
the panel width `W` / band unit `u` (`u ≈ 0.34·W`, vertically centred):

| element | x | y (from band top) | notes |
|---|---|---|---|
| legibility scrim | 0 → 0.74 W | full height | always drawn (any art stays readable) |
| series pill | left margin | 0.05 u | rounded, accent fill, readable text = `Panel.title` |
| **giant verb** | left margin | under pill | role `heavy`, fit ≤0.66 W × 0.38 u, white + shadow = `Panel.verb` |
| subtitle | left margin | under verb | bold white = `Panel.subtitle` |
| badge row | left margin | under subtitle | 1st = solid accent, rest = solid dark = `Panel.badges` |

New `Panel` fields: `verb` (string) and `badges` (list). If `verb` is empty it
falls back to `tag_main`, so the layout is safe even when used manually.

---

## 5 · Polish guarantees ("always looks perfect")

- **Text always fits** — every text element auto-shrinks to its box (`FontBook.fit`).
- **Always legible** — `verbforward` carries its own left→right scrim; rank/news
  layouts use scrims + readable-text-colour picks, so white text never sits on white.
- **Never broken art** — no image found → a themed gradient (line-up/news) or an
  accent placeholder with the name's initials (ranking). The card still reads.
- **Coherent colour** — accents come from the event mood (gold=returns,
  violet=leak, crimson=finale…) or the art palette; pill text auto-contrasts.
- **Clean text** — verbs are CAPS; series names are de-noised; dates normalised
  (`JUNE 28` → `On June 28`); label fillers trimmed.
- **Safe limits** — line-ups cap at *series-per-card*; rankings cap to what fits
  the canvas; ambiguous input falls back to a single news post.
- **Always editable** — Auto only seeds the plan. Every field, the template, the
  mode, the photo framing, and the per-account branding remain editable.

---

## Worked examples

```
Hunter x Hunter returns on June 28
Bleach Hell Arc — leak, not yet official
Berserk new chapters ongoing
→ line-up · verbforward "returns"
  [Hunter x Hunter | RETURNS | On June 28]
  [Bleach Hell Arc | RETURNING | Not Yet Official | LEAK · UNCONFIRMED]
  [Berserk | RETURNS | New Chapters Ongoing]

TOP 10 FEMALE CHARACTERS / 1. Frieren — Frieren / 2. Anya — Spy x Family …
→ ranking · corner

Solo Leveling Season 3 premieres July 4   → news · release
One Piece chapter 1120 leaked online       → news · breaking (LEAK)
Chainsaw Man movie drops a new trailer     → news · poster
Jujutsu Kaisen movie delayed to 2027       → news · breaking
```
