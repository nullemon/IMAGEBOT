"""End-to-end orchestration: news -> panels -> art/logos -> style variants."""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import logos
from .compositor import render_cards, render_cover, save_cards
from .fonts import FontBook
from .image_search import download_best, fetch_url_to_file
from .models import Panel, NewsPost, RankingList, RankEntry
from .news_parser import parse_news, parse_news_post, parse_ranking
from .newscard import render_news, save_news, NEWS_TEMPLATES, DEFAULT_NEWS
from .rankcard import render_ranking, save_ranking, RANK_TEMPLATES, DEFAULT_RANK
from .providers import get_text_provider, get_image_provider
from .styles import all_styles, get_style

_NEWS_NAME = {k: n for k, n, _ in NEWS_TEMPLATES}
_RANK_NAME = {k: n for k, n in RANK_TEMPLATES}
RANK_MAX = 20                     # most entries we'll keep from a pasted list

_FONTS = FontBook()

# named output sizes for the UI / CLI
SIZES = {
    "portrait": (1080, 1350),   # 4:5 feed (default)
    "square": (1080, 1080),     # 1:1 feed
    "story": (1080, 1920),      # 9:16 stories/reels
    "landscape": (1280, 720),   # 16:9
}


def _spec(settings, opts, **extra):
    """A CardSpec honouring the chosen output size (opts.width/height)."""
    extra.setdefault("width", opts.width or settings.card_width)
    extra.setdefault("height", opts.height or settings.card_height)
    return settings.card_spec(**extra)


@dataclass
class GenerateOptions:
    provider: str | None = None
    panels_per_card: int = 4
    watermark: str | None = None
    event_name: str | None = None
    date_text: str | None = None
    max_panels: int = 8
    # art
    find_art: bool = True
    vision_pick: bool = True            # use the AI provider to pick the cleanest image
    clean_art: bool = False             # OCR + inpaint to remove watermarks/text (GPU)
    ai_fallback: bool = False           # generate art when none found (cloud or local SD)
    # logos
    find_logo: bool = False             # auto search+download a transparent logo
    # accounts — render the post once per handle (max 4), each branded with its @username
    accounts: list = field(default_factory=list)   # [{handle, watermark, event_name, event_badge, accent}]
    # output size (None -> settings default 1080x1350)
    width: int | None = None
    height: int | None = None
    # output
    styles: list[str] | None = None     # which style keys to render (None = all)
    write_caption: bool = True
    cover_title: str = "LINE-UP"
    prefix: str = "card"


@dataclass
class GenerateResult:
    panels: list[Panel]
    variants: list[dict] = field(default_factory=list)   # [{key,name,cards:[...]}]
    card_paths: list[str] = field(default_factory=list)  # single-style convenience
    caption: str = ""
    provider_used: str = "none"
    runid: str = ""
    warnings: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
def _ai_generate_art(panel: Panel, settings, provider_name: str | None) -> str | None:
    prov = get_image_provider(settings, provider_name)
    if prov is None:
        return None
    prompt = (f"{panel.title}, dynamic character portrait, cinematic dramatic "
              "lighting, wide banner composition")
    data = prov.generate_image(prompt, size="1536x1024")
    if not data:
        return None
    from .image_search import CACHE_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"ai_{abs(hash(panel.title)) % (10**10)}.png"
    try:
        from PIL import Image
        Image.open(io.BytesIO(data)).convert("RGB").save(out)
        return str(out)
    except Exception:
        return None


def resolve_art(panels: list[Panel], settings, opts: GenerateOptions,
                provider=None, progress=None) -> list[str]:
    warnings: list[str] = []

    def log(m):
        if progress:
            progress(m)

    for i, p in enumerate(panels, 1):
        # logos: explicit -> library -> optional search
        try:
            logos.resolve_logo(p, settings, provider, do_search=opts.find_logo)
        except Exception:
            pass

        if p.image_path and Path(p.image_path).exists():
            continue
        if p.image_url:
            log(f"[{i}/{len(panels)}] downloading provided image for {p.title}")
            path = fetch_url_to_file(p.image_url, p.title)
            if path:
                p.image_path = path
                continue
        if opts.find_art:
            log(f"[{i}/{len(panels)}] finding art for “{p.title}”"
                + (" (AI vision pick)" if (opts.vision_pick and provider) else ""))
            path = download_best(
                p.search_query(), settings,
                provider=(provider if opts.vision_pick else None),
                clean=opts.clean_art)
            if path:
                p.image_path = path
                continue
        if opts.ai_fallback:
            log(f"[{i}/{len(panels)}] generating art for “{p.title}”")
            path = _ai_generate_art(p, settings, opts.provider)
            if path:
                p.image_path = path
                continue
        warnings.append(f"No art for “{p.title}” — used a themed gradient.")
    return warnings


def _apply_brand(spec, opts):
    if opts.watermark is not None:
        spec.brand.watermark = opts.watermark
    if opts.event_name:
        spec.brand.event_name = opts.event_name
    return spec


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "default"


def account_brands(opts: "GenerateOptions", settings) -> list[dict]:
    """One brand override per selected account (≤4), or a single default brand."""
    accs = opts.accounts or []
    if not accs:
        return [{"handle": "",
                 "watermark": (opts.watermark if opts.watermark is not None else settings.brand.watermark),
                 "event_name": opts.event_name or settings.brand.event_name,
                 "event_badge": settings.brand.event_badge, "accent": ""}]
    out = []
    for a in accs[:4]:
        h = (a.get("handle") or "").strip()
        wm = a.get("watermark") or (h.lstrip("@").upper() if h else settings.brand.watermark)
        out.append({"handle": h, "watermark": wm,
                    "event_name": a.get("event_name") or opts.event_name or settings.brand.event_name,
                    "event_badge": a.get("event_badge") or settings.brand.event_badge,
                    "accent": a.get("accent") or ""})
    return out


def _apply_account(spec, b):
    spec.brand.watermark = b["watermark"]
    spec.brand.event_name = b["event_name"]
    spec.brand.event_badge = b["event_badge"]
    return spec


def render_variants(panels: list[Panel], settings, opts: GenerateOptions,
                    runid: str, progress=None) -> list[dict]:
    keys = opts.styles or [s.key for s in all_styles()]
    out = []
    for k in keys:
        style = get_style(k)
        spec = _spec(settings, opts, panels_per_card=opts.panels_per_card)
        spec.style = style
        _apply_brand(spec, opts)
        cards = render_cards(panels, spec, _FONTS)
        paths = save_cards(cards, f"{settings.output_dir}/{runid}/{style.key}", prefix="card")
        out.append({"key": style.key, "name": style.name, "cards": paths})
        if progress:
            progress(f"styled: {style.name}")
    return out


_CAPTION_SYSTEM = (
    "You write punchy Instagram captions for an anime news account. Given a list "
    "of announcements, write ONE caption: a short hooky first line, a clean list "
    "of the titles with their status, then 8-15 relevant hashtags on the last "
    "line. Use tasteful emoji. Keep it under 600 characters. Return plain text.")


def write_caption(panels, settings, opts, provider=None) -> str:
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    event = opts.event_name or settings.brand.event_name
    if prov is not None:
        try:
            body = "\n".join(f"- {p.title} ({p.tag_main}"
                             + (f", {p.date_text}" if p.date_text else "") + ")"
                             for p in panels)
            return prov.complete_text(_CAPTION_SYSTEM, f"Event: {event}\n{body}",
                                      max_tokens=400).strip()
        except Exception:
            pass
    tags = "#anime #animenews #manga #anime2026 " + " ".join(
        "#" + "".join(ch for ch in p.title.lower() if ch.isalnum()) for p in panels[:6])
    return (f"🚨 BIG drops from {event}! 🔥\n\n" + "\n".join(
        f"▫️ {p.title} — {p.tag_main}" + (f" ({p.date_text})" if p.date_text else "")
        for p in panels) + f"\n\nWhich are you hyped for? 👇\n\n{tags}")


def make_variants(settings, opts: GenerateOptions | None = None, news: str | None = None,
                  panels: list[Panel] | None = None, progress=None) -> GenerateResult:
    """Parse (or take) panels, resolve art/logos once, render every style."""
    opts = opts or GenerateOptions()
    prov = get_text_provider(settings, opts.provider)
    provider_used = getattr(prov, "name", "none")

    if panels is None:
        if progress:
            progress(f"parsing news (provider: {provider_used})")
        panels = parse_news(news or "", settings, provider=prov,
                            max_panels=opts.max_panels,
                            default_tag_sub=settings.brand.default_tag_sub)
    if not panels:
        return GenerateResult(panels=[], warnings=["No panels could be parsed."],
                              provider_used=provider_used)
    if opts.date_text:
        for p in panels:
            if not p.date_text:
                p.date_text = opts.date_text

    warnings = resolve_art(panels, settings, opts, provider=prov, progress=progress)
    runid = time.strftime("%Y%m%d-%H%M%S")
    if progress:
        progress(f"rendering {len(opts.styles or all_styles())} style variants…")
    variants = render_variants(panels, settings, opts, runid, progress=progress)

    res = GenerateResult(panels=panels, variants=variants, runid=runid,
                         provider_used=provider_used, warnings=warnings)
    if variants:
        res.card_paths = variants[0]["cards"]
    if opts.write_caption:
        if progress:
            progress("writing caption…")
        res.caption = write_caption(panels, settings, opts, provider=prov)
    try:
        from . import enhance
        res.capabilities = enhance.capabilities()
    except Exception:
        res.capabilities = {}
    return res


def build_carousel(panels: list[Panel], settings, opts: GenerateOptions,
                   style_key: str, runid: str, with_cover: bool = True) -> dict:
    """Render the chosen style's cards (+ optional cover) and zip them."""
    opts = opts or GenerateOptions()
    style = get_style(style_key)
    b = account_brands(opts, settings)[0]
    spec = _spec(settings, opts, panels_per_card=opts.panels_per_card)
    spec.style = style
    _apply_account(spec, b)
    out_dir = Path(settings.output_dir) / runid / style.key / _slug(b["handle"] or b["watermark"])
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = save_cards(render_cards(panels, spec, _FONTS), str(out_dir), prefix="card")
    if with_cover:
        cover = render_cover(panels, spec, _FONTS, title=opts.cover_title)
        cover_path = out_dir / "00_cover.png"
        cover.convert("RGB").save(cover_path, "PNG")
        paths = [str(cover_path)] + paths

    zip_path = out_dir / "carousel.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, p in enumerate(paths, 1):
            zf.write(p, arcname=f"{i:02d}.png")
    return {"cards": paths, "zip": str(zip_path)}


def render_one(panels: list[Panel], settings, opts: GenerateOptions | None,
               style_key: str, runid: str) -> list[dict]:
    """Render ONE style for already-resolved panels — fast, no art search.
    Returns one output per account: [{account, cards:[...]}]."""
    opts = opts or GenerateOptions()
    style = get_style(style_key)
    outputs = []
    for b in account_brands(opts, settings):
        spec = _spec(settings, opts, panels_per_card=opts.panels_per_card)
        spec.style = style
        _apply_account(spec, b)
        sub = _slug(b["handle"] or b["watermark"])
        cards = save_cards(render_cards(panels, spec, _FONTS),
                           f"{settings.output_dir}/{runid}/{style.key}/{sub}", prefix="card")
        outputs.append({"account": b["handle"] or b["watermark"] or "", "cards": cards})
    return outputs


def prepare_lineup(settings, opts: GenerateOptions, news: str | None = None,
                   panels: list[Panel] | None = None, progress=None) -> dict:
    """Parse + resolve art/logos + caption once (no rendering)."""
    prov = get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    if panels is None:
        if progress:
            progress(f"parsing news (provider: {pu})")
        panels = parse_news(news or "", settings, provider=prov, max_panels=opts.max_panels,
                            default_tag_sub=settings.brand.default_tag_sub)
    if not panels:
        return {"panels": [], "warnings": ["No panels could be parsed."], "provider_used": pu, "caption": ""}
    if opts.date_text:
        for p in panels:
            if not p.date_text:
                p.date_text = opts.date_text
    warnings = resolve_art(panels, settings, opts, provider=prov, progress=progress)
    caption = write_caption(panels, settings, opts, provider=prov) if opts.write_caption else ""
    return {"panels": panels, "warnings": warnings, "provider_used": pu, "caption": caption}


# ==========================================================================
# News posts (single-story templates)
# ==========================================================================
@dataclass
class NewsResult:
    post: NewsPost
    runid: str = ""
    current: dict = field(default_factory=dict)   # {key, name, cards:[...]}
    caption: str = ""
    provider_used: str = "none"
    warnings: list = field(default_factory=list)
    log: list = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)


_NEWS_CAPTION_SYSTEM = (
    "Write ONE Instagram caption for a single anime-news post. A short hooky "
    "line restating the news, then 8-15 relevant hashtags on the last line. "
    "Tasteful emoji. Under 500 characters. Plain text.")


def _resolve_post_art(post: NewsPost, settings, opts: GenerateOptions, provider, progress):
    warnings = []
    if post.image_path and Path(post.image_path).exists():
        return warnings
    if post.image_url:
        if progress:
            progress("downloading provided image")
        p = fetch_url_to_file(post.image_url, post.headline[:40] or "news")
        if p:
            post.image_path = p
            return warnings
    if opts.find_art:
        if progress:
            progress(f"finding art for the story" + (" (AI pick)" if (opts.vision_pick and provider) else ""))
        p = download_best(post.search_query(), settings,
                          provider=(provider if opts.vision_pick else None), clean=opts.clean_art)
        if p:
            post.image_path = p
            return warnings
    if opts.ai_fallback:
        ip = get_image_provider(settings, opts.provider)
        if ip is not None:
            data = ip.generate_image(f"{post.headline}, anime key visual, cinematic, no text",
                                     size="1024x1280")
            if data:
                from .image_search import CACHE_DIR
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                out = CACHE_DIR / f"ai_news_{abs(hash(post.headline)) % (10**10)}.png"
                try:
                    from PIL import Image
                    Image.open(io.BytesIO(data)).convert("RGB").save(out)
                    post.image_path = str(out)
                    return warnings
                except Exception:
                    pass
    warnings.append("No art found — used a themed gradient.")
    return warnings


def render_news_one(post: NewsPost, settings, opts: GenerateOptions | None,
                    template_key: str, runid: str) -> list[dict]:
    """Render ONE news template for a resolved post — one output per account,
    each stamped with that account's @handle. [{account, cards:[...]}]."""
    opts = opts or GenerateOptions()
    outputs = []
    for b in account_brands(opts, settings):
        spec = _spec(settings, opts)
        _apply_account(spec, b)
        p = NewsPost.from_dict(post.to_dict())
        if b["handle"]:
            p.source = b["handle"]
        card = render_news(p, template_key, spec, _FONTS)
        sub = _slug(b["handle"] or b["watermark"])
        cards = save_news(card, f"{settings.output_dir}/{runid}/news_{template_key}/{sub}", prefix="post")
        outputs.append({"account": b["handle"] or b["watermark"] or "", "cards": cards})
    return outputs


def prepare_news(settings, opts: GenerateOptions, news: str, progress=None) -> dict:
    prov = get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    if progress:
        progress(f"parsing the story (provider: {pu})")
    post = parse_news_post(news, settings, provider=prov)
    if not post.headline:
        return {"post": post, "warnings": ["Couldn't read a headline."], "provider_used": pu, "caption": ""}
    if post.items and not post.body:
        post.body = "\n".join(str(x) for x in post.items)
    if opts.date_text and not post.date_text:
        post.date_text = opts.date_text
    warnings = _resolve_post_art(post, settings, opts, prov, progress)
    caption = news_caption(post, settings, opts, provider=prov) if opts.write_caption else ""
    return {"post": post, "warnings": warnings, "provider_used": pu, "caption": caption}


def news_caption(post: NewsPost, settings, opts, provider=None) -> str:
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    if prov is not None:
        try:
            return prov.complete_text(_NEWS_CAPTION_SYSTEM, post.headline, max_tokens=300).strip()
        except Exception:
            pass
    tag = "#anime #animenews #manga " + "#" + "".join(c for c in post.headline.lower() if c.isalnum())[:24]
    return f"🚨 {post.headline}\n\n{tag}"


def make_news_post(news: str, settings, opts: GenerateOptions | None = None,
                   template_key: str | None = None, progress=None) -> NewsResult:
    opts = opts or GenerateOptions()
    prep = prepare_news(settings, opts, news, progress=progress)
    post = prep["post"]
    if not post.headline:
        return NewsResult(post=post, warnings=prep["warnings"], provider_used=prep["provider_used"])
    runid = time.strftime("%Y%m%d-%H%M%S")
    key = template_key or DEFAULT_NEWS
    if progress:
        progress("rendering the post…")
    outputs = render_news_one(post, settings, opts, key, runid)
    res = NewsResult(post=post, runid=runid, provider_used=prep["provider_used"],
                     warnings=prep["warnings"], caption=prep["caption"],
                     current={"key": key, "name": _NEWS_NAME.get(key, key), "outputs": outputs})
    try:
        from . import enhance
        res.capabilities = enhance.capabilities()
    except Exception:
        res.capabilities = {}
    return res


def render_news_from_post(post: NewsPost, settings, opts: GenerateOptions, runid: str,
                          template_key: str) -> NewsResult:
    """Re-render a (possibly edited) post into a template — re-resolves art."""
    prov = get_text_provider(settings, opts.provider)
    warnings = _resolve_post_art(post, settings, opts, prov, None)
    outputs = render_news_one(post, settings, opts, template_key, runid)
    return NewsResult(post=post, runid=runid, warnings=warnings,
                      provider_used=getattr(prov, "name", "none"),
                      current={"key": template_key, "name": _NEWS_NAME.get(template_key, template_key), "outputs": outputs})


# ---- single-style helpers (CLI / back-compat) ----------------------------
def generate_from_news(text: str, settings, opts: GenerateOptions | None = None,
                       progress=None) -> GenerateResult:
    opts = opts or GenerateOptions()
    opts.styles = opts.styles or ["classic"]
    res = make_variants(settings, opts, news=text, progress=progress)
    return res


def render_panels(panels: list[Panel], settings, opts: GenerateOptions | None = None,
                  progress=None, **_) -> GenerateResult:
    opts = opts or GenerateOptions()
    return make_variants(settings, opts, panels=panels, progress=progress)


# ==========================================================================
# Ranking lists (Top-N, Anime-Corner style)
# ==========================================================================
@dataclass
class RankingResult:
    ranking: RankingList
    runid: str = ""
    current: dict = field(default_factory=dict)   # {key, name, outputs:[...]}
    caption: str = ""
    provider_used: str = "none"
    warnings: list = field(default_factory=list)
    log: list = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)


_RANK_CAPTION_SYSTEM = (
    "Write ONE Instagram caption for an anime Top-N ranking post. A hooky first "
    "line naming the list, optionally the top 3, then 8-15 relevant hashtags on "
    "the last line. Tasteful emoji. Under 500 characters. Plain text.")


def _resolve_ranking_art(rl: RankingList, settings, opts: GenerateOptions, provider, progress):
    warnings = []
    n = len(rl.entries)
    for i, e in enumerate(rl.entries, 1):
        if e.image_path and Path(e.image_path).exists():
            continue
        if e.image_url:
            if progress:
                progress(f"[{i}/{n}] downloading image for {e.name}")
            p = fetch_url_to_file(e.image_url, e.name or f"rank{i}")
            if p:
                e.image_path = p
                continue
        if opts.find_art:
            if progress:
                progress(f"[{i}/{n}] finding art for “{e.name}”"
                         + (" (AI pick)" if (opts.vision_pick and provider) else ""))
            p = download_best(e.search_query(), settings,
                              provider=(provider if opts.vision_pick else None),
                              clean=opts.clean_art)
            if p:
                e.image_path = p
                continue
        warnings.append(f"No art for “{e.name}” — used a placeholder.")
    return warnings


def ranking_caption(rl: RankingList, settings, opts, provider=None) -> str:
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    if prov is not None:
        try:
            body = rl.title + "\n" + "\n".join(
                f"{e.rank}. {e.name}" + (f" — {e.source}" if e.source else "")
                for e in rl.entries)
            return prov.complete_text(_RANK_CAPTION_SYSTEM, body, max_tokens=350).strip()
        except Exception:
            pass
    tags = "#anime #animeranking #anime2026 " + " ".join(
        "#" + "".join(c for c in e.name.lower() if c.isalnum()) for e in rl.entries[:5])
    lines = "\n".join(f"{e.rank}. {e.name}" + (f" — {e.source}" if e.source else "")
                      for e in rl.entries[:10])
    return f"🏆 {rl.title}!\n\n{lines}\n\nDo you agree? 👇\n\n{tags}"


def render_ranking_one(rl: RankingList, settings, opts: GenerateOptions | None,
                       template_key: str, runid: str) -> list[dict]:
    """Render ONE ranking template for a resolved list — one output per account,
    each stamped with that account's brand in the header. [{account, cards:[...]}]."""
    opts = opts or GenerateOptions()
    outputs = []
    for b in account_brands(opts, settings):
        spec = _spec(settings, opts)
        _apply_account(spec, b)
        card = render_ranking(rl, template_key, spec, _FONTS)
        sub = _slug(b["handle"] or b["watermark"])
        cards = save_ranking(card, f"{settings.output_dir}/{runid}/rank_{template_key}/{sub}",
                             prefix="ranking")
        outputs.append({"account": b["handle"] or b["watermark"] or "", "cards": cards})
    return outputs


def prepare_ranking(settings, opts: GenerateOptions, news: str, progress=None) -> dict:
    prov = get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    if progress:
        progress(f"parsing the list (provider: {pu})")
    rl = parse_ranking(news, settings, provider=prov, max_entries=RANK_MAX)
    if not rl.entries:
        return {"ranking": rl, "warnings": ["Couldn't read any list entries."],
                "provider_used": pu, "caption": ""}
    warnings = _resolve_ranking_art(rl, settings, opts, prov, progress)
    caption = ranking_caption(rl, settings, opts, provider=prov) if opts.write_caption else ""
    return {"ranking": rl, "warnings": warnings, "provider_used": pu, "caption": caption}


def make_ranking(news: str, settings, opts: GenerateOptions | None = None,
                 template_key: str | None = None, progress=None) -> RankingResult:
    opts = opts or GenerateOptions()
    prep = prepare_ranking(settings, opts, news, progress=progress)
    rl = prep["ranking"]
    if not rl.entries:
        return RankingResult(ranking=rl, warnings=prep["warnings"],
                             provider_used=prep["provider_used"])
    runid = time.strftime("%Y%m%d-%H%M%S")
    key = template_key or DEFAULT_RANK
    if progress:
        progress("rendering the ranking…")
    outputs = render_ranking_one(rl, settings, opts, key, runid)
    res = RankingResult(ranking=rl, runid=runid, provider_used=prep["provider_used"],
                        warnings=prep["warnings"], caption=prep["caption"],
                        current={"key": key, "name": _RANK_NAME.get(key, key), "outputs": outputs})
    try:
        from . import enhance
        res.capabilities = enhance.capabilities()
    except Exception:
        res.capabilities = {}
    return res


def render_ranking_from_list(rl: RankingList, settings, opts: GenerateOptions, runid: str,
                             template_key: str) -> RankingResult:
    """Re-render a (possibly edited) list into a template — re-resolves art."""
    prov = get_text_provider(settings, opts.provider)
    warnings = _resolve_ranking_art(rl, settings, opts, prov, None)
    outputs = render_ranking_one(rl, settings, opts, template_key, runid)
    return RankingResult(ranking=rl, runid=runid, warnings=warnings,
                         provider_used=getattr(prov, "name", "none"),
                         current={"key": template_key, "name": _RANK_NAME.get(template_key, template_key),
                                  "outputs": outputs})


# ==========================================================================
# Auto-design — paste anything, the brain picks mode + template + fields
# ==========================================================================
def prepare_auto(settings, opts: GenerateOptions, text: str, progress=None) -> dict:
    """Classify the pasted text and resolve art/caption for whatever it is.
    Returns a dict shaped per the chosen mode (panels | post | ranking) plus
    the picked template and a human 'why', ready for the matching payload."""
    from .autopilot import auto_design
    prov = get_text_provider(settings, opts.provider)
    pu = getattr(prov, "name", "none")
    plan = auto_design(text, settings, opts, provider=prov, progress=progress)
    out = {"mode": plan.mode, "template": plan.template, "why": plan.why,
           "provider_used": pu, "size": plan.size}
    if plan.mode == "ranking":
        rl = plan.ranking
        out["warnings"] = _resolve_ranking_art(rl, settings, opts, prov, progress)
        out["ranking"] = rl
        out["caption"] = ranking_caption(rl, settings, opts, provider=prov) if opts.write_caption else ""
    elif plan.mode == "news":
        post = plan.post
        if post.items and not post.body:
            post.body = "\n".join(str(x) for x in post.items)
        if opts.date_text and not post.date_text:
            post.date_text = opts.date_text
        out["warnings"] = _resolve_post_art(post, settings, opts, prov, progress)
        out["post"] = post
        out["caption"] = news_caption(post, settings, opts, provider=prov) if opts.write_caption else ""
    else:
        panels = plan.panels
        if opts.date_text:
            for p in panels:
                if not p.date_text:
                    p.date_text = opts.date_text
        out["warnings"] = resolve_art(panels, settings, opts, provider=prov, progress=progress)
        out["panels"] = panels
        out["caption"] = write_caption(panels, settings, opts, provider=prov) if opts.write_caption else ""
    return out


def make_auto(text: str, settings, opts: GenerateOptions | None = None, progress=None) -> dict:
    """One-shot auto pipeline (CLI): classify → render the picked template."""
    opts = opts or GenerateOptions()
    ap = prepare_auto(settings, opts, text, progress=progress)
    runid = time.strftime("%Y%m%d-%H%M%S")
    mode, key = ap["mode"], ap["template"]
    if mode == "ranking":
        ap["outputs"] = render_ranking_one(ap["ranking"], settings, opts, key, runid)
    elif mode == "news":
        ap["outputs"] = render_news_one(ap["post"], settings, opts, key, runid)
    else:
        ap["outputs"] = render_one(ap["panels"], settings, opts, key, runid)
    ap["runid"] = runid
    return ap
