"""Find and download character art for a series.

Backends are tried in order of quality:
  1. SerpApi (Google Images)      — needs SERPAPI_KEY
  2. Google Programmable Search   — needs GOOGLE_API_KEY + GOOGLE_CSE_ID
  3. DuckDuckGo images (keyless)  — via the `ddgs` package
  4. Bing Images HTML scrape      — last-resort, no key

Downloaded candidates are scored (resolution + landscape-ish aspect) and the
best is cached under cache/ so re-renders are instant. Everything fails soft:
on any error the caller gets None and the compositor uses a gradient instead.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import requests
from PIL import Image

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
CACHE_DIR = Path("cache")
MIN_W, MIN_H = 640, 320
MAX_BYTES = 18 * 1024 * 1024


# --------------------------------------------------------------------------
# backends -> list of candidate image URLs
# --------------------------------------------------------------------------
def _serpapi(query: str, key: str, limit: int) -> list[str]:
    r = requests.get("https://serpapi.com/search.json", timeout=20, params={
        "engine": "google_images", "q": query, "api_key": key, "num": limit,
    })
    r.raise_for_status()
    return [it["original"] for it in r.json().get("images_results", []) if it.get("original")][:limit]


def _google_cse(query: str, key: str, cx: str, limit: int) -> list[str]:
    r = requests.get("https://www.googleapis.com/customsearch/v1", timeout=20, params={
        "key": key, "cx": cx, "q": query, "searchType": "image",
        "num": min(limit, 10), "imgSize": "large", "safe": "off",
    })
    r.raise_for_status()
    return [it["link"] for it in r.json().get("items", []) if it.get("link")][:limit]


def _ddg(query: str, limit: int) -> list[str]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # older package name
        except ImportError:
            return []
    urls: list[str] = []
    with DDGS() as ddgs:
        for r in ddgs.images(query, max_results=limit):
            u = r.get("image") or r.get("url")
            if u:
                urls.append(u)
    return urls[:limit]


def _bing(query: str, limit: int) -> list[str]:
    from bs4 import BeautifulSoup
    import json as _json

    r = requests.get("https://www.bing.com/images/search", timeout=20, headers=HEADERS,
                     params={"q": query, "form": "HDRSC2"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    urls: list[str] = []
    for a in soup.select("a.iusc"):
        m = a.get("m")
        if not m:
            continue
        try:
            murl = _json.loads(m).get("murl")
            if murl:
                urls.append(murl)
        except Exception:
            continue
    return urls[:limit]


def search_image_urls(query: str, settings, limit: int = 12) -> list[str]:
    """Return candidate image URLs from the best available backend."""
    backends = []
    if settings.serpapi_key:
        backends.append(lambda: _serpapi(query, settings.serpapi_key, limit))
    if settings.google_api_key and settings.google_cse_id:
        backends.append(lambda: _google_cse(query, settings.google_api_key,
                                             settings.google_cse_id, limit))
    backends.append(lambda: _ddg(query, limit))
    backends.append(lambda: _bing(query, limit))

    for backend in backends:
        try:
            urls = backend()
            if urls:
                return urls
        except Exception:
            continue
    return []


# --------------------------------------------------------------------------
# download + score
# --------------------------------------------------------------------------
def _download(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=20, headers=HEADERS, stream=True)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "image" not in ctype and not url.lower().split("?")[0].endswith(
                (".jpg", ".jpeg", ".png", ".webp")):
            return None
        data = r.content
        if not data or len(data) > MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _score(img: Image.Image) -> float:
    w, h = img.size
    if w < MIN_W or h < MIN_H:
        return 0.0
    area = w * h
    ar = w / h
    # prefer landscape banners (cover-cropped into a wide panel); kill portraits
    if ar >= 1.2:
        bonus = 1.0 if ar <= 2.6 else 0.7
    elif ar >= 0.9:
        bonus = 0.55
    else:
        bonus = 0.2
    return area * bonus


def _cache_path(query: str) -> Path:
    h = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{h}.jpg"


def _jpeg_bytes(img: Image.Image, max_side: int = 512) -> bytes:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=82)
    return buf.getvalue()


def download_best(query: str, settings, max_candidates: int = 8,
                  use_cache: bool = True, provider=None, clean: bool = False,
                  do_upscale: bool = True) -> str | None:
    """Search, download candidates, pick the best (vision if a provider is given,
    else a resolution/aspect heuristic), optionally clean watermarks + upscale.
    Returns a local cached path, or None."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(query)
    if use_cache and cached.exists():
        return str(cached)

    urls = search_image_urls(query, settings, limit=max_candidates * 2)
    cands: list[tuple[Image.Image, float]] = []
    for url in urls:
        if len(cands) >= max_candidates:
            break
        img = _download(url)
        if img is None:
            continue
        sc = _score(img)
        if sc > 0:
            cands.append((img, sc))
    if not cands:
        return None

    cands.sort(key=lambda c: c[1], reverse=True)
    winner = cands[0][0]

    # vision pick among the top heuristic candidates
    if provider is not None and len(cands) > 1:
        topk = cands[:min(5, len(cands))]
        try:
            idx = provider.pick_image([_jpeg_bytes(c[0]) for c in topk])
            if idx is not None:
                winner = topk[idx][0]
        except Exception:
            pass

    # optional local enhancement (no-ops if libs/GPU absent)
    if clean:
        try:
            from . import enhance
            winner = enhance.clean_plate(winner)
        except Exception:
            pass
    if do_upscale:
        try:
            from . import enhance
            winner = enhance.upscale(winner)
        except Exception:
            pass

    winner.convert("RGB").save(cached, "JPEG", quality=92)
    return str(cached)


def fetch_url_to_file(url: str, query_hint: str = "explicit") -> str | None:
    """Download an explicit image URL (panel.image_url) to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    img = _download(url)
    if img is None:
        return None
    p = _cache_path(query_hint + "::" + url)
    img.save(p, "JPEG", quality=90)
    return str(p)
