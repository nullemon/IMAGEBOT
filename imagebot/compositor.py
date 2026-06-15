"""The compositing engine: build the stacked anime-news card with Pillow.

A card is a portrait image (default 1080x1350, Instagram 4:5) made of N stacked
panels. Each panel = background art + legibility scrims + series logo/title +
tag pills + right-side event wordmark + big date, matching the reference style.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .fonts import FontBook
from .models import CardSpec, Panel

WHITE = (255, 255, 255)
NEAR_BLACK = (20, 20, 22)


# --------------------------------------------------------------------------
# colour + image helpers
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
    """Black on light pills, white on dark pills."""
    return NEAR_BLACK if relative_luminance(bg) > 0.55 else WHITE


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
    """Scale + crop `img` to exactly fill w x h, biasing the crop toward focus."""
    img = img.convert("RGBA")
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    max_x, max_y = nw - w, nh - h
    left = int(max_x * focus_x)
    top = int(max_y * focus_y)
    return img.crop((left, top, left + w, top + h))


def _alpha_scrim(w: int, h: int, color, a_left: int, a_right: int) -> Image.Image:
    """RGBA overlay whose alpha ramps horizontally from a_left to a_right."""
    mask = Image.new("L", (w, 1))
    mpx = mask.load()
    for x in range(w):
        t = x / max(w - 1, 1)
        mpx[x, 0] = _lerp(a_left, a_right, t)
    mask = mask.resize((w, h))
    scrim = Image.new("RGBA", (w, h), color + (0,))
    scrim.putalpha(mask)
    return scrim


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def draw_text(draw, xy, text, font, fill, shadow=True,
              shadow_fill=(0, 0, 0, 170), shadow_off=(2, 3)):
    """Draw text at top-left xy, correcting for the font's bbox offset."""
    if not text:
        return (0, 0)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    x, y = xy[0] - l, xy[1] - t
    if shadow:
        draw.text((x + shadow_off[0], y + shadow_off[1]), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)
    return (r - l, b - t)


def draw_pill(draw, xy, text, font, bg, fg=None, pad_x=22, pad_y=12, radius=None):
    """Rounded pill with centered text. Returns (width, height)."""
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
# theme selection
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


def panel_accent(panel: Panel, spec: CardSpec, theme: dict) -> tuple[int, int, int]:
    return hex_to_rgb(panel.accent or theme.get("accent") or spec.brand.accent)


# --------------------------------------------------------------------------
# panel rendering
# --------------------------------------------------------------------------
def render_panel(panel: Panel, w: int, h: int, fonts: FontBook, spec: CardSpec) -> Image.Image:
    theme = pick_theme(panel, spec)
    accent = panel_accent(panel, spec, theme)

    # 1) background: art (cover) or themed gradient
    base: Image.Image | None = None
    if panel.image_path and Path(panel.image_path).exists():
        try:
            base = cover_resize(Image.open(panel.image_path), w, h)
        except Exception:
            base = None
    if base is None:
        base = vertical_gradient(w, h, hex_to_rgb(theme["top"]), hex_to_rgb(theme["bottom"]))

    # 2) legibility scrims — dark on the left (logo/tags) + softer on the right (date)
    base.alpha_composite(_alpha_scrim(int(w * 0.66), h, (0, 0, 0), 215, 0))
    right_w = int(w * 0.46)
    base.alpha_composite(_alpha_scrim(right_w, h, (0, 0, 0), 0, 150), (w - right_w, 0))
    # gentle overall darken for consistent text contrast
    base.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, 38)))

    draw = ImageDraw.Draw(base)
    ml = int(w * 0.045)          # left margin
    mr = int(w * 0.045)          # right margin
    right_edge = w - mr

    # Layout uses a stable "band unit" so it looks right whether the panel is a
    # short strip (4-per-card) or a tall block (1-per-card). The content band is
    # vertically centered within the panel.
    u = min(h, int(w * 0.34))
    cy0 = (h - u) // 2

    # 3) series logo / title (upper-left)
    logo_role = fonts.logo_role(panel.logo_style)
    title = panel.title.strip() or "UNTITLED"
    title_role = fonts.role_for_text(title, logo_role) or logo_role
    title_max_w = int(w * 0.46)
    title_font = fonts.fit(draw, title, title_role, title_max_w, int(u * 0.34),
                           start=int(u * 0.42))
    tx, ty = ml, cy0 + int(u * 0.17)
    _, title_h = draw_text(draw, (tx, ty), title, title_font, WHITE)

    cursor_y = ty + title_h + int(u * 0.04)
    # subtitle — skip rather than render tofu boxes if it's CJK with no CJK font
    sub_role = fonts.role_for_text(panel.subtitle.strip(), "ui_regular") if panel.subtitle.strip() else None
    if sub_role:
        sub_font = fonts.fit(draw, panel.subtitle, sub_role, title_max_w,
                             int(u * 0.10), start=int(u * 0.13))
        _, sub_h = draw_text(draw, (tx, cursor_y), panel.subtitle, sub_font,
                             (235, 235, 240))
        cursor_y += sub_h + int(u * 0.04)

    # 4) tag pills row
    pill_font = fonts.font("ui", max(14, int(u * 0.05)))
    px = ml
    if panel.tag_main.strip():
        pw, _ = draw_pill(draw, (px, cursor_y), panel.tag_main.upper(), pill_font,
                          accent, pad_x=int(w * 0.02), pad_y=int(u * 0.035))
        px += pw + int(w * 0.012)
    if panel.tag_sub.strip():
        draw_pill(draw, (px, cursor_y), panel.tag_sub.upper(), pill_font,
                  (245, 245, 248), NEAR_BLACK, pad_x=int(w * 0.02), pad_y=int(u * 0.035))

    # 5) event wordmark (top-right):  [badge] ANIME EXPO
    brand = spec.brand
    wm_font = fonts.font("ui", max(16, int(u * 0.085)))
    badge_txt = brand.event_badge.strip()
    name_txt = brand.event_name.strip().upper()
    bl, bt, br, bb = draw.textbbox((0, 0), name_txt or "EXPO", font=wm_font)
    name_w, name_h = br - bl, bb - bt
    badge_w = 0
    badge_pad = int(name_h * 0.28)
    if badge_txt:
        bbl, bbt, bbr, bbb = draw.textbbox((0, 0), badge_txt, font=wm_font)
        badge_w = (bbr - bbl) + 2 * badge_pad
    gap = int(w * 0.012)
    group_w = badge_w + (gap if badge_w else 0) + name_w
    gx = right_edge - group_w
    gy = cy0 + int(u * 0.15)
    if badge_txt:
        bh = name_h + 2 * badge_pad
        draw.rounded_rectangle([gx, gy - badge_pad, gx + badge_w, gy - badge_pad + bh],
                               radius=int(bh * 0.18), fill=WHITE)
        draw_text(draw, (gx + badge_pad, gy), badge_txt, wm_font, NEAR_BLACK, shadow=False)
        gx += badge_w + gap
    draw_text(draw, (gx, gy), name_txt, wm_font, WHITE)

    # 6) big date (right-aligned, below wordmark)
    date_txt = (panel.date_text or "").strip().upper()
    if date_txt:
        date_font = fonts.fit(draw, date_txt, "date", int(w * 0.42), int(u * 0.5),
                              start=int(u * 0.62))
        dl, dt, dr, db = draw.textbbox((0, 0), date_txt, font=date_font)
        dx = right_edge - (dr - dl) - dl
        dy = cy0 + int(u * 0.38)
        draw_text(draw, (dx, dy), date_txt, date_font, WHITE, shadow_off=(3, 4))

    return base


# --------------------------------------------------------------------------
# card assembly
# --------------------------------------------------------------------------
def render_card(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> Image.Image:
    fonts = fonts or FontBook()
    n = max(1, len(panels))
    W, H = spec.width, spec.height
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    base_h = H // n
    y = 0
    for i, panel in enumerate(panels):
        ph = H - y if i == n - 1 else base_h  # last panel absorbs rounding
        card.alpha_composite(render_panel(panel, W, ph, fonts, spec), (0, y))
        if spec.divider and i < n - 1:
            ImageDraw.Draw(card).line([(0, y + ph - 1), (W, y + ph - 1)],
                                      fill=(0, 0, 0, 220), width=2)
        y += ph

    # watermark — sit it on the panel seam nearest the centre (subtle, like the
    # reference cards); for a single panel drop it low so it clears the content.
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


def render_cards(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> list[Image.Image]:
    """Chunk panels into cards of `panels_per_card` and render each."""
    fonts = fonts or FontBook()
    per = max(1, spec.panels_per_card)
    cards = []
    for i in range(0, len(panels), per):
        cards.append(render_card(panels[i:i + per], spec, fonts))
    return cards


def save_cards(cards: list[Image.Image], out_dir: str, prefix: str = "card") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, card in enumerate(cards, 1):
        p = out / (f"{prefix}_{i}.png" if len(cards) > 1 else f"{prefix}.png")
        card.convert("RGB").save(p, "PNG")
        paths.append(str(p))
    return paths
