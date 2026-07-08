"""Font resolution + auto-sizing.

Ships with a curated set of open-source display fonts under assets/fonts/.
Falls back to DejaVu (bundled with most systems / Pillow) and finally to
Pillow's built-in bitmap font, so rendering never hard-fails.
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

ASSETS = Path(__file__).resolve().parent / "assets" / "fonts"

# Role -> ordered candidate filenames (first that exists wins).
ROLE_FILES: dict[str, list[str]] = {
    "date": ["BigShoulders-Bold.ttf"],          # huge condensed date
    "logo_sans": ["BigShoulders-Bold.ttf", "Outfit-Bold.ttf"],
    "logo_heavy": ["Boldonse-Regular.ttf", "EricaOne-Regular.ttf"],
    "logo_serif": ["Gloock-Regular.ttf", "CrimsonPro-Bold.ttf"],
    "ui": ["BricolageGrotesque-Bold.ttf", "WorkSans-Bold.ttf", "Outfit-Bold.ttf"],
    "ui_regular": ["BricolageGrotesque-Regular.ttf", "WorkSans-Bold.ttf"],
    # CJK (Japanese/Chinese/Korean) — for titles/subtitles like "進撃の巨人".
    # Tried as bundled first, then common system/absolute paths below.
    "cjk": ["NotoSansJP-Bold.ttf", "NotoSansCJK-Bold.ttf", "NotoSansJP-Regular.ttf"],
}

# System fallbacks (DejaVu ships with Pillow on most platforms).
_SYS_BOLD = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"]
_SYS_REGULAR = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]
# CJK-capable fonts commonly present across OSes (absolute paths + bare names).
_SYS_CJK = [
    "/etc/alternatives/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",  # macOS
    "/Library/Fonts/Arial Unicode.ttf",            # macOS
    "C:/Windows/Fonts/msgothic.ttc",               # Windows
    "C:/Windows/Fonts/YuGothM.ttc",
    "NotoSansCJK-Regular.ttc",
    "msgothic.ttc",
]

_LOGO_STYLE_TO_ROLE = {
    "sans": "logo_sans",
    "serif": "logo_serif",
    "heavy": "logo_heavy",
    "auto": "logo_sans",
}


class FontBook:
    """Resolves font files for roles and caches sized ImageFont objects."""

    def __init__(self) -> None:
        self._path_cache: dict[str, str | None] = {}
        self._font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    # -- path resolution ---------------------------------------------------
    def _resolve_path(self, role: str) -> str | None:
        if role in self._path_cache:
            return self._path_cache[role]
        candidates = list(ROLE_FILES.get(role, []))
        # try bundled assets
        for name in candidates:
            p = ASSETS / name
            if p.exists():
                self._path_cache[role] = str(p)
                return str(p)
        # system fallback (CJK roles get CJK fonts; others bold/regular)
        if role == "cjk":
            sysfonts = _SYS_CJK
        elif role.endswith("regular"):
            sysfonts = _SYS_REGULAR
        else:
            sysfonts = _SYS_BOLD
        for name in sysfonts:
            try:
                ImageFont.truetype(name, 24)  # probe
                self._path_cache[role] = name
                return name
            except Exception:
                continue
        self._path_cache[role] = None
        return None

    def font(self, role: str, size: int) -> ImageFont.FreeTypeFont:
        size = max(8, int(size))
        key = (role, size)
        if key in self._font_cache:
            return self._font_cache[key]
        path = self._resolve_path(role)
        try:
            f = ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except Exception:
            f = ImageFont.load_default()
        self._font_cache[key] = f
        return f

    def logo_role(self, logo_style: str) -> str:
        return _LOGO_STYLE_TO_ROLE.get((logo_style or "auto").lower(), "logo_sans")

    # -- CJK handling ------------------------------------------------------
    @staticmethod
    def has_cjk(text: str) -> bool:
        """True if text contains CJK / Japanese kana characters."""
        for ch in text or "":
            o = ord(ch)
            if (0x3040 <= o <= 0x30FF or   # hiragana + katakana
                    0x3400 <= o <= 0x9FFF or   # CJK ideographs
                    0xF900 <= o <= 0xFAFF or
                    0xFF66 <= o <= 0xFF9D):    # half-width katakana
                return True
        return False

    def cjk_available(self) -> bool:
        return self._resolve_path("cjk") is not None

    def role_for_text(self, text: str, base_role: str) -> str | None:
        """Pick a font role for `text`. Returns None if it can't be rendered
        (CJK text but no CJK font installed) so the caller can skip it."""
        if self.has_cjk(text):
            return "cjk" if self.cjk_available() else None
        return base_role

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def measure(draw, text: str, font) -> tuple[int, int]:
        """Return (width, height) of text with the given font."""
        if not text:
            return (0, 0)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return (r - l, b - t)

    def fit(
        self,
        draw,
        text: str,
        role: str,
        max_w: int,
        max_h: int,
        start: int = 200,
        minimum: int = 12,
    ) -> ImageFont.FreeTypeFont:
        """Largest font (for `role`) where `text` fits within max_w x max_h.
        Always measures at least once, so a start <= minimum still shrinks-to-fit
        down to the floor instead of returning an unmeasured font."""
        size = max(int(start), minimum)
        while True:
            f = self.font(role, size)
            w, h = self.measure(draw, text, f)
            if (w <= max_w and h <= max_h) or size <= minimum:
                return f
            # shrink proportionally to converge fast, then step down
            ratio = min(max_w / max(w, 1), max_h / max(h, 1))
            nxt = int(size * ratio) if ratio < 1 else size - 4
            size = max(minimum, min(nxt, size - 1))
