"""The compositing engine: build the stacked anime-news card with Pillow.

A card is a portrait image (default 1080x1350, Instagram 4:5) made of N stacked
panels. Each panel = background art + treatment (per the chosen Style) + series
logo/title + tag pills + event wordmark + big date, matching the reference look.

The look is driven by a `styles.Style` carried on `CardSpec.style`. The default
("Classic Expo") reproduces the reference cards; other presets restyle the same
panels (cutout, duotone, neon, noir, cinematic, …) so the user can pick.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageFilter

from .fonts import FontBook
from .models import CardSpec, Panel
from .styles import Style, DEFAULT_STYLE

WHITE = (255, 255, 255)
NEAR_BLACK = (20, 20, 22)


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def hex_to_rgb(value: str, default=(40, 40, 44)) -> tuple[int, int, int]:
    if not value:
        return default
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except Exception:
        return default


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def relative_luminance(rgb) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_text_color(bg) -> tuple[int, int, int]:
    return NEAR_BLACK if relative_luminance(bg) > 0.55 else WHITE


def vibrant_color(img: Image.Image, fallback=(245, 166, 35)) -> tuple[int, int, int]:
    """Pick a punchy accent colour from the art (most saturated mid-bright pixel)."""
    try:
        small = img.convert("RGB").resize((40, 40))
        hsv = small.convert("HSV")
        rgb = small.load()
        h = hsv.load()
        best, best_score = fallback, -1.0
        for y in range(40):
            for x in range(40):
                _, s, v = h[x, y]
                if v < 60 or v > 240:
                    continue
                score = (s / 255) * (1 - abs(v - 170) / 170)
                if score > best_score:
                    best_score, best = score, rgb[x, y]
        return best
    except Exception:
        return fallback


# --------------------------------------------------------------------------
# image building blocks
# --------------------------------------------------------------------------
def vertical_gradient(w: int, h: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = (_lerp(top[0], bottom[0], t),
                    _lerp(top[1], bottom[1], t),
                    _lerp(top[2], bottom[2], t))
    return grad.resize((w, h)).convert("RGBA")


def cover_resize(img: Image.Image, w: int, h: int,
                 focus_x: float = 0.6, focus_y: float = 0.38) -> Image.Image:
    img = img.convert("RGBA")
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = int((nw - w) * focus_x), int((nh - h) * focus_y)
    return img.crop((left, top, left + w, top + h))


def _alpha_scrim(w: int, h: int, color, a_left: int, a_right: int) -> Image.Image:
    mask = Image.new("L", (w, 1))
    mpx = mask.load()
    for x in range(w):
        mpx[x, 0] = _lerp(a_left, a_right, x / max(w - 1, 1))
    mask = mask.resize((w, h))
    scrim = Image.new("RGBA", (w, h), color + (0,))
    scrim.putalpha(mask)
    return scrim


def _vertical_alpha(w: int, h: int, color, a_top: int, a_bottom: int) -> Image.Image:
    mask = Image.new("L", (1, h))
    mpx = mask.load()
    for y in range(h):
        mpx[0, y] = _lerp(a_top, a_bottom, y / max(h - 1, 1))
    mask = mask.resize((w, h))
    scrim = Image.new("RGBA", (w, h), color + (0,))
    scrim.putalpha(mask)
    return scrim


def duotone(img: Image.Image, dark, light) -> Image.Image:
    gray = img.convert("L")
    return ImageOps.colorize(gray, black=dark, white=light).convert("RGBA")


def apply_vignette(base: Image.Image, amount: float) -> None:
    w, h = base.size
    mask = Image.radial_gradient("L").resize((w, h))  # 0 center -> 255 edge
    mask = mask.point(lambda v: int(v * amount))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.putalpha(mask)
    base.alpha_composite(overlay)


def apply_grain(base: Image.Image, amount: float) -> None:
    w, h = base.size
    noise = Image.effect_noise((w, h), 28).convert("L")
    overlay = Image.merge("RGBA", (noise, noise, noise,
                                   noise.point(lambda v: int(amount * 80))))
    base.alpha_composite(overlay)


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def draw_text(draw, xy, text, font, fill, shadow=True,
              shadow_fill=(0, 0, 0, 170), shadow_off=(2, 3)):
    if not text:
        return (0, 0)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    x, y = xy[0] - l, xy[1] - t
    if shadow:
        draw.text((x + shadow_off[0], y + shadow_off[1]), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)
    return (r - l, b - t)


def draw_pill(draw, xy, text, font, bg, fg=None, pad_x=22, pad_y=12, radius=None):
    fg = fg or readable_text_color(bg)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    rw, rh = tw + 2 * pad_x, th + 2 * pad_y
    x, y = xy
    rad = rh // 2 if radius is None else radius
    draw.rounded_rectangle([x, y, x + rw, y + rh], radius=rad, fill=bg)
    draw.text((x + pad_x - l, y + pad_y - t), text, font=font, fill=fg)
    return (rw, rh)


# --------------------------------------------------------------------------
# theme + art
# --------------------------------------------------------------------------
def pick_theme(panel: Panel, spec: CardSpec) -> dict:
    themes = spec.themes or {}
    if panel.theme and panel.theme != "auto" and panel.theme in themes:
        return themes[panel.theme]
    if not themes:
        return {"top": "#1a1a1f", "bottom": "#33333d", "accent": spec.brand.accent}
    keys = sorted(themes.keys())
    idx = int(hashlib.md5(panel.title.encode("utf-8")).hexdigest(), 16) % len(keys)
    return themes[keys[idx]]


def _open_art(panel: Panel) -> Image.Image | None:
    if panel.image_path and Path(panel.image_path).exists():
        try:
            return Image.open(panel.image_path).convert("RGB")
        except Exception:
            return None
    return None


def _cutout(panel: Panel) -> Image.Image | None:
    """Subject cut-out (RGBA) via the optional local enhance layer (rembg)."""
    if not (panel.image_path and Path(panel.image_path).exists()):
        return None
    try:
        from . import enhance
        return enhance.remove_background(panel.image_path)
    except Exception:
        return None


def _accent(panel, spec, theme, style: Style, art) -> tuple[int, int, int]:
    if panel.accent:
        return hex_to_rgb(panel.accent)
    if style.accent_mode == "fixed" and style.accent:
        return hex_to_rgb(style.accent)
    if style.accent_mode == "series" and art is not None:
        return vibrant_color(art, hex_to_rgb(theme.get("accent", spec.brand.accent)))
    return hex_to_rgb(theme.get("accent") or spec.brand.accent)


def _styled_backdrop(w, h, theme, style) -> Image.Image:
    if style.bg == "solid" and style.solid:
        return Image.new("RGBA", (w, h), hex_to_rgb(style.solid) + (255,))
    top, bottom = hex_to_rgb(theme["top"]), hex_to_rgb(theme["bottom"])
    return vertical_gradient(w, h, top, bottom)


def _build_background(panel, w, h, style: Style, theme, accent) -> Image.Image:
    art = _open_art(panel)

    # cutout-based styles
    if style.bg in ("art_cutout", "art_blur_cutout"):
        cut = _cutout(panel)
        if cut is not None:
            base = _styled_backdrop(w, h, theme, style)
            if style.bg == "art_blur_cutout" and art is not None:
                bg = cover_resize(art, w, h).filter(ImageFilter.GaussianBlur(style.blur or 16))
                bg.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, 70)))
                base = bg
            if style.glow:
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                gd = ImageDraw.Draw(glow)
                cx, cy = int(w * 0.6), int(h * 0.55)
                rr = int(h * 0.6)
                gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=accent + (130,))
                base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(h * 0.18))))
            # place subject, anchored bottom-right, ~92% panel height
            ch = int(h * 0.92)
            cw = max(1, int(cut.width * ch / cut.height))
            cut = cut.resize((cw, ch), Image.LANCZOS)
            base.alpha_composite(cut, (int(w * 0.52), h - ch))
            return base
        # no cutout available -> fall through to full-art with extra mood

    if art is not None:
        base = cover_resize(art, w, h)
        if style.bg == "art_duotone" and style.duotone:
            base = duotone(base, hex_to_rgb(style.duotone[0]), hex_to_rgb(style.duotone[1]))
        elif style.grayscale:
            base = ImageOps.grayscale(base).convert("RGBA")
        if style.blur:
            base = base.filter(ImageFilter.GaussianBlur(style.blur))
        return base

    return _styled_backdrop(w, h, theme, style)


# --------------------------------------------------------------------------
# logo / title block
# --------------------------------------------------------------------------
def _title_role(style: Style, panel: Panel, fonts: FontBook) -> str:
    if style.title_role and style.title_role != "auto":
        return fonts.logo_role(style.title_role)
    return fonts.logo_role(panel.logo_style)


def _draw_logo_block(draw, base, panel, fonts, style, w, u, top_y, max_w,
                     align="left", left=0):
    """Draw the logo image (if any) or the styled title text. Returns bottom y."""
    # logo image overlay
    if panel.logo_path and Path(panel.logo_path).exists():
        try:
            logo = Image.open(panel.logo_path).convert("RGBA")
            mh = int(u * 0.34 * max(0.3, panel.logo_scale))
            mw = int(max_w * max(0.3, panel.logo_scale))
            scale = min(mw / logo.width, mh / logo.height)
            logo = logo.resize((max(1, int(logo.width * scale)),
                                max(1, int(logo.height * scale))), Image.LANCZOS)
            lx = (w - logo.width) // 2 if align == "center" else left
            base.alpha_composite(logo, (lx, top_y))
            return top_y + logo.height
        except Exception:
            pass
    # text title
    title = panel.title.strip() or "UNTITLED"
    role = fonts.role_for_text(title, _title_role(style, panel, fonts)) or _title_role(style, panel, fonts)
    font = fonts.fit(draw, title, role, max_w, int(u * 0.34), start=int(u * 0.42))
    l, t, r, b = draw.textbbox((0, 0), title, font=font)
    tx = (w - (r - l)) // 2 if align == "center" else left
    draw_text(draw, (tx, top_y), title, font, WHITE)
    return top_y + (b - t)


# --------------------------------------------------------------------------
# panel rendering
# --------------------------------------------------------------------------
def render_panel(panel: Panel, w: int, h: int, fonts: FontBook, spec: CardSpec) -> Image.Image:
    style: Style = spec.style or DEFAULT_STYLE
    theme = pick_theme(panel, spec)
    art_for_accent = _open_art(panel)
    accent = _accent(panel, spec, theme, style, art_for_accent)

    base = _build_background(panel, w, h, style, theme, accent)

    # tint wash
    if style.tint:
        base.alpha_composite(Image.new("RGBA", (w, h), hex_to_rgb(style.tint) + (style.tint_alpha,)))
    # overall darken
    if style.darken:
        base.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, style.darken)))
    # scrims
    if style.scrim_left:
        base.alpha_composite(_alpha_scrim(int(w * 0.66), h, (0, 0, 0), style.scrim_left, 0))
    if style.scrim_right:
        rw = int(w * 0.46)
        base.alpha_composite(_alpha_scrim(rw, h, (0, 0, 0), 0, style.scrim_right), (w - rw, 0))
    if style.scrim_bottom:
        bh = int(h * 0.5)
        base.alpha_composite(_vertical_alpha(w, bh, (0, 0, 0), 0, style.scrim_bottom), (0, h - bh))
    # effects
    if style.vignette:
        apply_vignette(base, style.vignette)
    if style.grain:
        apply_grain(base, style.grain)
    if style.bars:
        bar = min(style.bars, h // 5)
        d0 = ImageDraw.Draw(base)
        d0.rectangle([0, 0, w, bar], fill=(0, 0, 0, 255))
        d0.rectangle([0, h - bar, w, h], fill=(0, 0, 0, 255))

    draw = ImageDraw.Draw(base)
    ml = int(w * 0.045)
    right_edge = w - ml
    u = min(h, int(w * 0.34))
    cy0 = (h - u) // 2
    centered = style.logo_align == "center"
    title_max_w = int(w * (0.62 if centered else 0.46))

    # ---- pills (computed, drawn under or above the logo) ----------------
    pill_font = fonts.font("ui", max(14, int(u * 0.05)))

    def draw_pills(y):
        items = []
        if panel.tag_main.strip():
            items.append((panel.tag_main.upper(), accent, None))
        if panel.tag_sub.strip():
            items.append((panel.tag_sub.upper(), style.pill_light, readable_text_color(style.pill_light)))
        total = 0
        sizes = []
        for txt, _, _ in items:
            l, t, r, b = draw.textbbox((0, 0), txt, font=pill_font)
            rw = (r - l) + 2 * int(w * 0.02)
            sizes.append(rw)
            total += rw
        total += int(w * 0.012) * max(0, len(items) - 1)
        px = (w - total) // 2 if centered else ml
        for (txt, bg, fg), rw in zip(items, sizes):
            draw_pill(draw, (px, y), txt, pill_font, bg, fg,
                      pad_x=int(w * 0.02), pad_y=int(u * 0.035))
            px += rw + int(w * 0.012)

    # ---- logo + pills ----------------------------------------------------
    if style.pill_pos == "top":
        py = cy0 + int(u * 0.06)
        draw_pills(py)
        logo_top = py + int(u * 0.16)
    else:
        logo_top = cy0 + int(u * 0.17)

    bottom = _draw_logo_block(draw, base, panel, fonts, style, w, u, logo_top,
                              title_max_w, align="center" if centered else "left", left=ml)

    cursor = bottom + int(u * 0.04)
    sub_role = fonts.role_for_text(panel.subtitle.strip(), "ui_regular") if panel.subtitle.strip() else None
    if sub_role:
        sub_font = fonts.fit(draw, panel.subtitle, sub_role, title_max_w, int(u * 0.10), start=int(u * 0.13))
        sl, st, sr, sb = draw.textbbox((0, 0), panel.subtitle, font=sub_font)
        sx = (w - (sr - sl)) // 2 if centered else ml
        draw_text(draw, (sx, cursor), panel.subtitle, sub_font, (235, 235, 240))
        cursor += (sb - st) + int(u * 0.04)

    if style.pill_pos != "top":
        draw_pills(cursor)

    # ---- event wordmark (always top-right, smaller in center layouts) ----
    _draw_wordmark(draw, base, spec, fonts, u, right_edge, cy0,
                   small=centered or style.date_pos != "right")

    # ---- date ------------------------------------------------------------
    # a centered, full-width logo would collide with a right-aligned date, so
    # push the date to the bottom whenever the logo is centered.
    date_pos = "bottom" if (centered and style.date_pos == "right") else style.date_pos
    _draw_date(draw, panel, fonts, w, h, u, cy0, right_edge, date_pos)

    return base


def _draw_wordmark(draw, base, spec, fonts, u, right_edge, cy0, small=False):
    brand = spec.brand
    size = max(14, int(u * (0.06 if small else 0.085)))
    wm_font = fonts.font("ui", size)
    badge_txt = brand.event_badge.strip()
    name_txt = brand.event_name.strip().upper()
    bl, bt, br, bb = draw.textbbox((0, 0), name_txt or "EXPO", font=wm_font)
    name_w, name_h = br - bl, bb - bt
    badge_w = 0
    badge_pad = int(name_h * 0.28)
    if badge_txt:
        bbl, _, bbr, _ = draw.textbbox((0, 0), badge_txt, font=wm_font)
        badge_w = (bbr - bbl) + 2 * badge_pad
    gap = int(name_h * 0.4)
    group_w = badge_w + (gap if badge_w else 0) + name_w
    gx = right_edge - group_w
    gy = cy0 + int(u * 0.14)
    if badge_txt:
        bh = name_h + 2 * badge_pad
        draw.rounded_rectangle([gx, gy - badge_pad, gx + badge_w, gy - badge_pad + bh],
                               radius=int(bh * 0.18), fill=WHITE)
        draw_text(draw, (gx + badge_pad, gy), badge_txt, wm_font, NEAR_BLACK, shadow=False)
        gx += badge_w + gap
    draw_text(draw, (gx, gy), name_txt, wm_font, WHITE)


def _draw_date(draw, panel, fonts, w, h, u, cy0, right_edge, date_pos):
    date_txt = (panel.date_text or "").strip().upper()
    if not date_txt or date_pos == "none":
        return
    if date_pos == "corner":
        f = fonts.font("date", int(u * 0.22))
        l, t, r, b = draw.textbbox((0, 0), date_txt, font=f)
        draw_text(draw, (right_edge - (r - l), cy0 + int(u * 0.78)), date_txt, f, WHITE)
        return
    if date_pos == "bottom":
        f = fonts.fit(draw, date_txt, "date", int(w * 0.8), int(u * 0.34), start=int(u * 0.5))
        l, t, r, b = draw.textbbox((0, 0), date_txt, font=f)
        draw_text(draw, ((w - (r - l)) // 2, cy0 + int(u * 0.72)), date_txt, f, WHITE, shadow_off=(3, 4))
        return
    # default: big, right-aligned
    f = fonts.fit(draw, date_txt, "date", int(w * 0.42), int(u * 0.5), start=int(u * 0.62))
    l, t, r, b = draw.textbbox((0, 0), date_txt, font=f)
    draw_text(draw, (right_edge - (r - l), cy0 + int(u * 0.38)), date_txt, f, WHITE, shadow_off=(3, 4))


# --------------------------------------------------------------------------
# card assembly
# --------------------------------------------------------------------------
def render_card(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> Image.Image:
    fonts = fonts or FontBook()
    style = spec.style or DEFAULT_STYLE
    n = max(1, len(panels))
    W, H = spec.width, spec.height
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    base_h = H // n
    y = 0
    for i, panel in enumerate(panels):
        ph = H - y if i == n - 1 else base_h
        card.alpha_composite(render_panel(panel, W, ph, fonts, spec), (0, y))
        if spec.divider and i < n - 1:
            ImageDraw.Draw(card).line([(0, y + ph - 1), (W, y + ph - 1)],
                                      fill=style.divider, width=2)
        y += ph

    if spec.brand.watermark:
        d = ImageDraw.Draw(card)
        wm = spec.brand.watermark.upper()
        f = fonts.font("ui", int(W * 0.034))
        l, t, r, b = d.textbbox((0, 0), wm, font=f)
        if n > 1:
            seams = [H * i // n for i in range(1, n)]
            wy = min(seams, key=lambda s: abs(s - H / 2))
        else:
            wy = int(H * 0.9)
        d.text(((W - (r - l)) // 2 - l, wy - (b - t) // 2 - t), wm, font=f,
               fill=(255, 255, 255, 70))
    return card


def render_cover(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None,
                 title: str = "LINE-UP") -> Image.Image:
    """A carousel cover slide: big event title + the list of series."""
    fonts = fonts or FontBook()
    W, H = spec.width, spec.height
    accent = hex_to_rgb(spec.brand.accent)
    base = vertical_gradient(W, H, (12, 12, 18), (26, 22, 42))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.08, H * 0.04, W * 0.92, H * 0.55],
                                 fill=accent + (90,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(170)))
    apply_vignette(base, 0.35)
    d = ImageDraw.Draw(base)

    # event wordmark, centered near the top
    ev = (spec.brand.event_badge + "  " if spec.brand.event_badge else "") + spec.brand.event_name.upper()
    ev_font = fonts.font("ui", int(W * 0.045))
    l, t, r, b = d.textbbox((0, 0), ev, font=ev_font)
    draw_text(d, ((W - (r - l)) // 2, int(H * 0.12)), ev, ev_font, WHITE)

    # big title
    tf = fonts.fit(d, title.upper(), "date", int(W * 0.86), int(H * 0.2), start=int(H * 0.18))
    l, t, r, b = d.textbbox((0, 0), title.upper(), font=tf)
    draw_text(d, ((W - (r - l)) // 2, int(H * 0.26)), title.upper(), tf, WHITE, shadow_off=(3, 4))

    # accent rule
    ry = int(H * 0.42)
    d.rounded_rectangle([W // 2 - int(W * 0.08), ry, W // 2 + int(W * 0.08), ry + 8],
                        radius=4, fill=accent)

    # series list
    lf = fonts.font("ui", int(W * 0.04))
    y = int(H * 0.5)
    for p in panels[:8]:
        line = p.title.upper()
        l, t, r, b = d.textbbox((0, 0), line, font=lf)
        draw_text(d, ((W - (r - l)) // 2, y), line, lf, (235, 235, 240))
        y += int((b - t) + H * 0.022)

    if spec.brand.watermark:
        wf = fonts.font("ui", int(W * 0.03))
        l, t, r, b = d.textbbox((0, 0), spec.brand.watermark.upper(), font=wf)
        draw_text(d, ((W - (r - l)) // 2, int(H * 0.93)), spec.brand.watermark.upper(),
                  wf, (255, 255, 255, 150), shadow=False)
    return base


def render_cards(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> list[Image.Image]:
    fonts = fonts or FontBook()
    per = max(1, spec.panels_per_card)
    return [render_card(panels[i:i + per], spec, fonts)
            for i in range(0, len(panels), per)]


def save_cards(cards: list[Image.Image], out_dir: str, prefix: str = "card") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, card in enumerate(cards, 1):
        p = out / (f"{prefix}_{i}.png" if len(cards) > 1 else f"{prefix}.png")
        card.convert("RGB").save(p, "PNG")
        paths.append(str(p))
    return paths
