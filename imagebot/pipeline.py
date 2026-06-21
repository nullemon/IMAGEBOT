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
from .models import Panel
from .news_parser import parse_news
from .providers import get_text_provider, get_image_provider
from .styles import all_styles, get_style

_FONTS = FontBook()


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


def render_variants(panels: list[Panel], settings, opts: GenerateOptions,
                    runid: str, progress=None) -> list[dict]:
    keys = opts.styles or [s.key for s in all_styles()]
    out = []
    for k in keys:
        style = get_style(k)
        spec = settings.card_spec(panels_per_card=opts.panels_per_card)
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
    spec = settings.card_spec(panels_per_card=opts.panels_per_card)
    spec.style = style
    _apply_brand(spec, opts)
    out_dir = Path(settings.output_dir) / runid / style.key
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
               style_key: str, runid: str) -> list[str]:
    """Render ONE style for already-resolved panels — fast, no art search.
    Used by the web UI to swap templates instantly."""
    opts = opts or GenerateOptions()
    style = get_style(style_key)
    spec = settings.card_spec(panels_per_card=opts.panels_per_card)
    spec.style = style
    _apply_brand(spec, opts)
    return save_cards(render_cards(panels, spec, _FONTS),
                      f"{settings.output_dir}/{runid}/{style.key}", prefix="card")


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
