"""Pick proper, good-looking colours from a key visual.

Extracts a vivid, readable accent (for pills / badges / date stamps) and a dark
tone (for gradients/scrims) from the art, so each post is colour-matched to its
image instead of using a flat default.
"""
from __future__ import annotations

import colorsys

from PIL import Image


def _hsv(rgb):
    return colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def _boost(rgb, min_s=0.58, lo_v=0.46, hi_v=0.86):
    """Nudge a colour to a vivid, legible accent (raise saturation, clamp value)."""
    h, s, v = _hsv(rgb)
    s = max(s, min_s)
    v = min(max(v, lo_v), hi_v)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def extract_palette(img: Image.Image, fallback=(245, 166, 35)) -> dict:
    """Return {'accent': (r,g,b), 'dark': (r,g,b), 'light': (r,g,b)}."""
    try:
        small = img.convert("RGB").resize((96, 96))
        q = small.quantize(colors=16, method=Image.FASTOCTREE)
        pal = q.getpalette()
        colors = [(count, tuple(pal[idx * 3:idx * 3 + 3])) for count, idx in q.getcolors()]
        total = sum(c for c, _ in colors) or 1

        # accent = the most "poster-worthy" colour: saturated, mid-bright, common
        best, best_score = None, -1.0
        for count, rgb in colors:
            h, s, v = _hsv(rgb)
            if v < 0.16 or v > 0.97 or s < 0.18:
                continue
            score = s * (0.35 + 0.65 * v) * (0.3 + 0.7 * (count / total) ** 0.4)
            if score > best_score:
                best_score, best = score, rgb
        if best is None:  # very muted image — take the most saturated pixel anyway
            best = max(colors, key=lambda c: _hsv(c[1])[1])[1]
        accent = _boost(best)

        dark = min(colors, key=lambda c: _hsv(c[1])[2])[1]
        light = max(colors, key=lambda c: _hsv(c[1])[2])[1]
        return {"accent": accent, "dark": dark, "light": light}
    except Exception:
        return {"accent": fallback, "dark": (20, 20, 26), "light": (235, 235, 240)}


def accent_of(img: Image.Image | None, fallback=(245, 166, 35)) -> tuple[int, int, int]:
    if img is None:
        return fallback
    return extract_palette(img, fallback)["accent"]
