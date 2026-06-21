"""Official-logo handling: a local library + upload + auto search/download.

Logos are transparent PNGs overlaid on the panel instead of the styled title.
They live in cache/logos/<slug>.png so once you add one (upload or auto-fetch)
it's reused for that title forever.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import requests
from PIL import Image

LIB = Path("cache") / "logos"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) imagebot/0.2"}


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-") or "logo"


def library_path(title: str) -> Path:
    return LIB / f"{slug(title)}.png"


def get_library_logo(title: str) -> str | None:
    p = library_path(title)
    return str(p) if p.exists() else None


def save_logo(title: str, src) -> str:
    """Store a logo (path / bytes / PIL image) as a trimmed transparent PNG."""
    LIB.mkdir(parents=True, exist_ok=True)
    if isinstance(src, Image.Image):
        img = src
    elif isinstance(src, (bytes, bytearray)):
        img = Image.open(io.BytesIO(src))
    else:
        img = Image.open(src)
    img = img.convert("RGBA")
    bbox = img.split()[3].getbbox()
    if bbox:
        img = img.crop(bbox)
    out = library_path(title)
    img.save(out)
    return str(out)


def _download_rgba(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=20, headers=UA)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return img.convert("RGBA")
    except Exception:
        return None


def _transparency_score(img: Image.Image) -> float:
    """Higher when the image is a clean logo: has real transparency, wide-ish."""
    if img.mode != "RGBA":
        return 0.0
    alpha = img.split()[3]
    extrema = alpha.getextrema()
    if extrema[0] >= 250:           # fully opaque -> not a cut-out logo
        return 0.1
    # fraction of transparent pixels (a logo is mostly empty space)
    hist = alpha.histogram()
    transparent = sum(hist[:24])
    total = img.width * img.height
    frac = transparent / max(total, 1)
    ar = img.width / max(img.height, 1)
    ar_bonus = 1.0 if 1.2 <= ar <= 6 else 0.6
    return (0.4 + frac) * ar_bonus


def search_logo(title: str, settings, provider=None, max_candidates: int = 6) -> str | None:
    """Find a transparent logo PNG online, pick the cleanest, save to the library."""
    from .image_search import search_image_urls
    query = f"{title} anime logo transparent png"
    urls = search_image_urls(query, settings, limit=max_candidates * 2)
    # prefer obvious PNG links first
    urls = sorted(urls, key=lambda u: (".png" not in u.lower()))
    best, best_score = None, 0.0
    tried = 0
    for u in urls:
        if tried >= max_candidates:
            break
        img = _download_rgba(u)
        if img is None or min(img.size) < 80:
            continue
        tried += 1
        sc = _transparency_score(img)
        if sc > best_score:
            best, best_score = img, sc
    if best is None or best_score < 0.3:
        return None
    return save_logo(title, best)


def resolve_logo(panel, settings, provider=None, do_search: bool = False) -> str | None:
    """Fill panel.logo_path from (1) explicit, (2) library, (3) optional search."""
    if panel.logo_path and Path(panel.logo_path).exists():
        return panel.logo_path
    lib = get_library_logo(panel.title)
    if lib:
        panel.logo_path = lib
        return lib
    if do_search:
        found = search_logo(panel.title, settings, provider)
        if found:
            panel.logo_path = found
            return found
    return None
