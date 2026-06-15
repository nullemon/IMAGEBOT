"""End-to-end orchestration: news -> panels -> art -> cards (+ caption)."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from .compositor import render_cards, save_cards
from .fonts import FontBook
from .image_search import download_best, fetch_url_to_file
from .models import Panel
from .news_parser import parse_news
from .providers import get_text_provider, get_image_provider


@dataclass
class GenerateOptions:
    provider: str | None = None         # text provider override (claude/openai/...)
    panels_per_card: int = 4
    variant: str = "classic"
    watermark: str | None = None        # override brand watermark
    event_name: str | None = None
    date_text: str | None = None        # apply this date to all panels if set
    max_panels: int = 8
    find_art: bool = True               # scrape Google/DDG for art
    ai_fallback: bool = False           # generate art with AI if none found
    write_caption: bool = True
    prefix: str = "card"


@dataclass
class GenerateResult:
    panels: list[Panel]
    card_paths: list[str] = field(default_factory=list)
    caption: str = ""
    provider_used: str = "none"
    warnings: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


_FONTS = FontBook()


def _ai_generate_art(panel: Panel, settings, provider_name: str | None) -> str | None:
    prov = get_image_provider(settings, provider_name)
    if prov is None:
        return None
    prompt = (f"Anime key visual of {panel.title}, dynamic character portrait, "
              "cinematic dramatic lighting, official anime production art, highly "
              "detailed, wide cinematic banner composition, no text, no logo")
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
                progress=None) -> list[str]:
    warnings: list[str] = []

    def log(msg: str):
        if progress:
            progress(msg)

    for i, p in enumerate(panels, 1):
        if p.image_path and Path(p.image_path).exists():
            continue
        if p.image_url:
            log(f"[{i}/{len(panels)}] downloading provided image for {p.title}")
            path = fetch_url_to_file(p.image_url, p.title)
            if path:
                p.image_path = path
                continue
        if opts.find_art:
            log(f"[{i}/{len(panels)}] searching art for “{p.title}”")
            path = download_best(p.search_query(), settings)
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
        log(f"[{i}/{len(panels)}] no art found for {p.title} (gradient fallback)")
    return warnings


_CAPTION_SYSTEM = (
    "You write punchy Instagram captions for an anime news account. Given a list "
    "of announcements, write ONE caption: a short hooky first line, a clean list "
    "of the titles with their status, then 8-15 relevant hashtags on the last "
    "line. Use tasteful emoji. Keep it under 600 characters. Return plain text.")


def write_caption(panels: list[Panel], settings, opts: GenerateOptions,
                  provider=None) -> str:
    prov = provider if provider is not None else get_text_provider(settings, opts.provider)
    lines = [f"- {p.title} ({p.tag_main}{', ' + p.date_text if p.date_text else ''})"
             for p in panels]
    body = "\n".join(lines)
    event = opts.event_name or settings.brand.event_name
    if prov is not None:
        try:
            return prov.complete_text(
                _CAPTION_SYSTEM,
                f"Event: {event}\nAnnouncements:\n{body}",
                max_tokens=400,
            ).strip()
        except Exception:
            pass
    # template fallback
    tags = "#anime #animenews #manga #anime2026 " + " ".join(
        "#" + "".join(ch for ch in p.title.lower() if ch.isalnum()) for p in panels[:6])
    return (f"🚨 BIG drops from {event}! 🔥\n\n" + "\n".join(
        f"▫️ {p.title} — {p.tag_main}" + (f" ({p.date_text})" if p.date_text else "")
        for p in panels) + f"\n\nWhich are you hyped for? 👇\n\n{tags}")


def generate_from_news(text: str, settings, opts: GenerateOptions | None = None,
                       progress=None) -> GenerateResult:
    opts = opts or GenerateOptions()
    prov = get_text_provider(settings, opts.provider)
    provider_used = getattr(prov, "name", "none")

    if progress:
        progress(f"parsing news with provider: {provider_used}")
    panels = parse_news(text, settings, provider=prov, max_panels=opts.max_panels,
                        default_tag_sub=settings.brand.default_tag_sub)
    if not panels:
        return GenerateResult(panels=[], warnings=["No panels could be parsed."],
                              provider_used=provider_used)

    if opts.date_text:
        for p in panels:
            if not p.date_text:
                p.date_text = opts.date_text

    return render_panels(panels, settings, opts, progress=progress,
                         provider=prov, provider_used=provider_used)


def render_panels(panels: list[Panel], settings, opts: GenerateOptions | None = None,
                  progress=None, provider=None, provider_used: str | None = None
                  ) -> GenerateResult:
    """Render already-structured panels (used by the web UI's edit-then-render)."""
    opts = opts or GenerateOptions()
    res = GenerateResult(panels=panels)
    res.provider_used = provider_used or getattr(
        provider or get_text_provider(settings, opts.provider), "name", "none")

    res.warnings += resolve_art(panels, settings, opts, progress=progress)

    spec = settings.card_spec(
        panels_per_card=opts.panels_per_card,
        variant=opts.variant,
    )
    if opts.watermark is not None:
        spec.brand.watermark = opts.watermark
    if opts.event_name:
        spec.brand.event_name = opts.event_name

    if progress:
        progress("compositing cards…")
    cards = render_cards(panels, spec, _FONTS)
    res.card_paths = save_cards(cards, settings.output_dir, prefix=opts.prefix)

    if opts.write_caption:
        if progress:
            progress("writing caption…")
        res.caption = write_caption(panels, settings, opts, provider=provider)
    return res
