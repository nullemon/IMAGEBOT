"""Optional local GPU/ML enhancements — aligned with the nullemon/mangatranslator
stack (the same proven setup), all auto-skip if a lib/model isn't present.

Clean-up pipeline reused from the manga translator:
  - text_mask()  : comic-text-detector (ONNX, GPU) → pixel-level text strokes,
                   with CRAFT (craft-text-detector) as a fallback detector.
  - clean_plate(): that mask → LaMa inpaint (simple-lama-inpainting), so source
                   text / watermarks are surgically erased from scraped art.
  - upscale()    : Real-ESRGAN (anime) via spandrel — rescue low-res raws.
IMAGEBOT-specific:
  - remove_background(): rembg (isnet-anime) cut-out for the "Spotlight" styles.

Install with:  bash scripts/setup_local.sh   (or pip install -r requirements-local.txt)
Everything degrades gracefully: missing lib/model/GPU → safe fallback or no-op.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import requests
from PIL import Image, ImageFilter

CACHE = Path("cache")
MODELS = Path("models")
_CUTOUT_DIR = CACHE / "cutouts"

# model weights (auto-downloaded on first use; same sources as mangatranslator)
COMIC_TEXT_URLS = [
    "https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx",
    "https://github.com/dmMaze/comic-text-detector/releases/download/data/comictextdetector.pt.onnx",
]
REALESRGAN_URLS = [
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
]
_COMIC_INPUT = 1024

# lazily-initialised singletons
_rembg_session = None
_ort_session = None
_craft = None
_sr_model = None
_lama = None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _as_image(src) -> Image.Image:
    return src if isinstance(src, Image.Image) else Image.open(src)


def _device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _cuda() -> bool:
    return _device() == "cuda"


def _key(src) -> str:
    if isinstance(src, (str, Path)):
        p = Path(src)
        st = p.stat()
        return hashlib.sha1(f"{p}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16]
    return hashlib.sha1(_as_image(src).tobytes()[:4096]).hexdigest()[:16]


def _ensure_weight(name: str, urls: list[str]) -> str | None:
    """Path to a model weight, downloading it once if missing. None on failure."""
    env = os.environ.get("TEXT_SEG_MODEL") if "comictextdetector" in name else None
    if env and Path(env).exists():
        return env
    MODELS.mkdir(parents=True, exist_ok=True)
    out = MODELS / name
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    for url in urls:
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp = out.with_suffix(out.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        fh.write(chunk)
                tmp.replace(out)
            return str(out)
        except Exception:
            continue
    return None


def capabilities() -> dict:
    import importlib.util as iu
    have = lambda m: iu.find_spec(m) is not None
    return {
        "cutout (rembg)": have("rembg"),
        "upscale (spandrel/Real-ESRGAN)": have("spandrel"),
        "text-detect (comic-text-detector/onnx)": have("onnxruntime"),
        "text-detect (CRAFT)": have("craft_text_detector"),
        "ocr (manga-ocr)": have("manga_ocr"),
        "inpaint (LaMa)": have("simple_lama_inpainting"),
        "torch+cuda": _cuda(),
    }


# --------------------------------------------------------------------------
# background removal (cutout) — IMAGEBOT styles
# --------------------------------------------------------------------------
def remove_background(src) -> Image.Image | None:
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
        try:
            _rembg_session = new_session("isnet-anime")
        except Exception:
            _rembg_session = new_session()
    try:
        out = remove(_as_image(src).convert("RGBA"), session=_rembg_session,
                     post_process_mask=True)
    except Exception:
        return None
    bbox = out.split()[3].getbbox()
    if bbox:
        out = out.crop(bbox)
    try:
        out.save(cache_path)
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# text detection — comic-text-detector (ONNX) primary, CRAFT fallback
# --------------------------------------------------------------------------
def _ort():
    global _ort_session
    if _ort_session is not None:
        return _ort_session
    try:
        import onnxruntime as ort
    except Exception:
        return None
    path = _ensure_weight("comictextdetector.pt.onnx", COMIC_TEXT_URLS)
    if not path:
        return None
    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"] if _cuda()
                 else ["CPUExecutionProvider"])
    try:
        _ort_session = ort.InferenceSession(path, providers=providers)
    except Exception:
        try:
            _ort_session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        except Exception:
            _ort_session = None
    return _ort_session


def _comic_text_mask(img_bgr):
    """Pixel-level text-stroke mask (uint8 0/255) via comic-text-detector ONNX."""
    sess = _ort()
    if sess is None:
        return None
    import numpy as np
    import cv2
    h, w = img_bgr.shape[:2]
    s = _COMIC_INPUT / max(h, w)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    resized = cv2.resize(img_bgr, (nw, nh))
    canvas = np.zeros((_COMIC_INPUT, _COMIC_INPUT, 3), dtype=np.uint8)
    canvas[:nh, :nw] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype("float32") / 255.0
    blob = np.transpose(rgb, (2, 0, 1))[None]  # (1,3,1024,1024)
    try:
        outs = sess.run(None, {sess.get_inputs()[0].name: blob})
    except Exception:
        return None
    strokes = [o for o in outs if getattr(o, "ndim", 0) == 4 and o.shape[1] == 1]
    if not strokes:
        return None
    m = max(strokes, key=lambda o: o.shape[2] * o.shape[3])[0, 0]
    if m.max() <= 1.5:
        m = m * 255.0
    m = np.clip(m, 0, 255).astype("uint8")
    m = cv2.resize(m, (_COMIC_INPUT, _COMIC_INPUT))[:nh, :nw]
    m = cv2.resize(m, (w, h))
    _, m = cv2.threshold(m, 60, 255, cv2.THRESH_BINARY)
    return m


def _craft():
    global _craft
    if _craft is not None:
        return _craft
    try:
        from craft_text_detector import Craft
        import torch
        _craft = Craft(output_dir=None, cuda=torch.cuda.is_available(),
                       crop_type="box", text_threshold=0.65,
                       link_threshold=0.35, low_text=0.35)
    except Exception:
        _craft = None
    return _craft


def _craft_mask(img_bgr):
    craft = _craft()
    if craft is None:
        return None
    import numpy as np
    import cv2
    try:
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        boxes = craft.detect_text(rgb).get("boxes")
    except Exception:
        return None
    if boxes is None or len(boxes) == 0:
        return None
    mask = np.zeros(img_bgr.shape[:2], dtype="uint8")
    for box in boxes:
        cv2.fillPoly(mask, [np.array(box, dtype="int32")], 255)
    return mask


def text_mask(src):
    """Return a uint8 (0/255) text mask, or None if no detector is available."""
    try:
        import numpy as np
        import cv2
    except Exception:
        return None
    img = _as_image(src).convert("RGB")
    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    return _comic_text_mask(bgr) if _ort() else _craft_mask(bgr)


def detect_text_regions(src) -> list[tuple[int, int, int, int]]:
    """[(x,y,w,h)] bounding boxes of detected text. [] if nothing/none."""
    m = text_mask(src)
    if m is None:
        return []
    import cv2
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 6 and h >= 6:
            out.append((int(x), int(y), int(w), int(h)))
    return out


def text_coverage(src) -> float:
    img = _as_image(src)
    boxes = detect_text_regions(img)
    if not boxes:
        return 0.0
    area = img.size[0] * img.size[1]
    return min(1.0, sum(bw * bh for _, _, bw, bh in boxes) / max(area, 1))


# --------------------------------------------------------------------------
# watermark / text removal — mask + LaMa (cv2.inpaint fallback)
# --------------------------------------------------------------------------
def clean_plate(src, blur_fallback: bool = True) -> Image.Image:
    img = _as_image(src).convert("RGB")
    try:
        import numpy as np
        import cv2
    except Exception:
        return img
    mask = text_mask(img)
    if mask is None or int(mask.max()) == 0:
        return img
    # dilate so we cover the full glyph + halo
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.dilate(mask, k, iterations=2)

    global _lama
    try:
        from simple_lama_inpainting import SimpleLama
        if _lama is None:
            _lama = SimpleLama()
        out = _lama(img, Image.fromarray(mask))
        return out.convert("RGB")
    except Exception:
        pass
    rgb = np.asarray(img)
    try:
        res = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, 5, cv2.INPAINT_TELEA)
        return Image.fromarray(cv2.cvtColor(res, cv2.COLOR_BGR2RGB))
    except Exception:
        if not blur_fallback:
            return img
        blurred = img.filter(ImageFilter.GaussianBlur(18))
        img.paste(blurred, (0, 0), Image.fromarray(mask))
        return img


# --------------------------------------------------------------------------
# super-resolution — Real-ESRGAN (anime) via spandrel
# --------------------------------------------------------------------------
def upscale(src, min_side: int = 700) -> Image.Image:
    img = _as_image(src).convert("RGB")
    if min(img.size) >= min_side:
        return img
    try:
        import numpy as np
        import torch
        from spandrel import ModelLoader
        path = _ensure_weight("RealESRGAN_x4plus_anime_6B.pth", REALESRGAN_URLS)
        if not path:
            raise RuntimeError("no weights")
        global _sr_model
        if _sr_model is None:
            _sr_model = ModelLoader().load_from_file(path).to(_device()).eval()
        arr = np.asarray(img).astype("float32") / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(_device())
        with torch.no_grad():
            out = _sr_model(t)
        out = out.squeeze(0).clamp_(0, 1).permute(1, 2, 0).cpu().numpy()
        return Image.fromarray((out * 255).round().astype("uint8"))
    except Exception:
        w, h = img.size
        return img.resize((w * 2, h * 2), Image.LANCZOS)
