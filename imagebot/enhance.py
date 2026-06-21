"""Optional local GPU/ML enhancements — all auto-skip if the lib isn't installed.

Designed for a local Ubuntu box with a GPU + plenty of RAM (the same kind of
stack a manga translator uses). Install the heavy deps with:

    pip install -r requirements-local.txt        # or scripts/setup_local.sh

Capabilities, each independent and optional:
  - remove_background()  : rembg (u2net/isnet) — cut the character out for the
                           "cutout" styles, so art looks designed, not pasted.
  - upscale()            : Real-ESRGAN — rescue low-res art before compositing.
  - detect_text_regions(): EasyOCR / PaddleOCR — find existing text/watermarks.
  - clean_plate()        : detect + LaMa inpaint (or blur) to remove watermarks.

Nothing here is required; every function falls back to a no-op/return-None so
the app works on a plain machine. `capabilities()` reports what's available.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageFilter

CACHE = Path("cache")
_CUTOUT_DIR = CACHE / "cutouts"
_rembg_session = None
_easyocr_reader = None
_esrgan = None


# --------------------------------------------------------------------------
def _as_image(src) -> Image.Image:
    return src if isinstance(src, Image.Image) else Image.open(src)


def _key(src) -> str:
    if isinstance(src, (str, Path)):
        p = Path(src)
        stat = p.stat()
        return hashlib.sha1(f"{p}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16]
    return hashlib.sha1(_as_image(src).tobytes()[:4096]).hexdigest()[:16]


def capabilities() -> dict:
    """Report which optional backends are importable (no models loaded)."""
    import importlib.util as iu
    have = lambda m: iu.find_spec(m) is not None
    return {
        "cutout (rembg)": have("rembg"),
        "upscale (realesrgan)": have("realesrgan"),
        "ocr (easyocr)": have("easyocr"),
        "ocr (paddleocr)": have("paddleocr"),
        "inpaint (simple_lama_inpainting)": have("simple_lama_inpainting"),
        "torch+cuda": _cuda_available(),
    }


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


# --------------------------------------------------------------------------
# background removal (cutout)
# --------------------------------------------------------------------------
def remove_background(src) -> Image.Image | None:
    """Return an RGBA cut-out of the subject, or None if rembg isn't installed."""
    try:
        from rembg import remove, new_session
    except Exception:
        return None

    _CUTOUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CUTOUT_DIR / f"{_key(src)}.png"
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGBA")
        except Exception:
            pass

    global _rembg_session
    if _rembg_session is None:
        # isnet-anime is tuned for anime/illustration subjects
        try:
            _rembg_session = new_session("isnet-anime")
        except Exception:
            _rembg_session = new_session()

    img = _as_image(src).convert("RGBA")
    try:
        out = remove(img, session=_rembg_session, post_process_mask=True)
    except Exception:
        return None
    out = _trim_alpha(out)
    try:
        out.save(cache_path)
    except Exception:
        pass
    return out


def _trim_alpha(img: Image.Image) -> Image.Image:
    """Crop transparent margins so the subject fills the frame."""
    if img.mode != "RGBA":
        return img
    bbox = img.split()[3].getbbox()
    return img.crop(bbox) if bbox else img


# --------------------------------------------------------------------------
# upscaling
# --------------------------------------------------------------------------
def upscale(src, scale: int = 2, min_side: int = 700) -> Image.Image:
    """Upscale small art with Real-ESRGAN; fall back to high-quality Lanczos."""
    img = _as_image(src).convert("RGB")
    if min(img.size) >= min_side:
        return img
    try:
        import numpy as np
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        global _esrgan
        if _esrgan is None:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                            num_grow_ch=32, scale=4)
            _esrgan = RealESRGANer(scale=4, model_path=
                "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                model=model, half=_cuda_available())
        out, _ = _esrgan.enhance(np.array(img), outscale=scale)
        return Image.fromarray(out)
    except Exception:
        w, h = img.size
        return img.resize((w * scale, h * scale), Image.LANCZOS)


# --------------------------------------------------------------------------
# OCR — text / watermark detection
# --------------------------------------------------------------------------
def detect_text_regions(src) -> list[tuple[int, int, int, int]]:
    """Return [(x, y, w, h)] boxes of detected text. [] if no OCR available."""
    img = _as_image(src).convert("RGB")
    # EasyOCR first (simple GPU detector), then PaddleOCR
    try:
        import numpy as np
        import easyocr
        global _easyocr_reader
        if _easyocr_reader is None:
            _easyocr_reader = easyocr.Reader(["en", "ja"], gpu=_cuda_available())
        boxes = []
        for pts, _txt, conf in _easyocr_reader.readtext(np.array(img)):
            if conf < 0.3:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            boxes.append((int(min(xs)), int(min(ys)),
                          int(max(xs) - min(xs)), int(max(ys) - min(ys))))
        return boxes
    except Exception:
        pass
    try:
        import numpy as np
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False,
                        use_gpu=_cuda_available())
        res = ocr.ocr(np.array(img), cls=False) or []
        boxes = []
        for line in res:
            for box, _ in (line or []):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                boxes.append((int(min(xs)), int(min(ys)),
                              int(max(xs) - min(xs)), int(max(ys) - min(ys))))
        return boxes
    except Exception:
        return []


def text_coverage(src) -> float:
    """Fraction of the image area covered by detected text (0..1).

    Useful for scoring/ranking scraped candidates — lower is cleaner art.
    """
    img = _as_image(src)
    boxes = detect_text_regions(img)
    if not boxes:
        return 0.0
    area = img.size[0] * img.size[1]
    return min(1.0, sum(bw * bh for _, _, bw, bh in boxes) / max(area, 1))


# --------------------------------------------------------------------------
# watermark / text removal
# --------------------------------------------------------------------------
def clean_plate(src, blur_fallback: bool = True) -> Image.Image:
    """Remove detected text/watermarks via LaMa inpainting, else blur the boxes."""
    img = _as_image(src).convert("RGB")
    boxes = detect_text_regions(img)
    if not boxes:
        return img
    mask = Image.new("L", img.size, 0)
    from PIL import ImageDraw
    md = ImageDraw.Draw(mask)
    pad = max(2, int(min(img.size) * 0.01))
    for x, y, bw, bh in boxes:
        md.rectangle([x - pad, y - pad, x + bw + pad, y + bh + pad], fill=255)
    try:
        from simple_lama_inpainting import SimpleLama
        lama = SimpleLama()
        return lama(img, mask).convert("RGB")
    except Exception:
        if not blur_fallback:
            return img
        blurred = img.filter(ImageFilter.GaussianBlur(18))
        img.paste(blurred, (0, 0), mask)
        return img
