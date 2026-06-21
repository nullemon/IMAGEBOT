#!/usr/bin/env bash
# Set up IMAGEBOT with the optional local GPU/ML stack on Ubuntu + NVIDIA.
# Mirrors the nullemon/mangatranslator GPU setup so it installs the same way.
# Safe to re-run. Everything heavy is optional; the app works without it.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Python venv"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip wheel

echo "==> Core requirements"
pip install -r requirements.txt

echo "==> GPU stack (torch / rembg / onnxruntime-gpu / lama / spandrel / manga-ocr)"
pip install -r requirements-local.txt || echo "!! some local extras failed — they're optional"

echo "==> CRAFT text detector (no-deps: its setup pins an ancient opencv)"
pip install --no-deps craft-text-detector || echo "!! craft-text-detector skipped (comic-text-detector still works)"

echo "==> CUDA 12 runtime libs for onnxruntime-gpu"
pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 nvidia-cudnn-cu12 \
    nvidia-cufft-cu12 nvidia-curand-cu12 2>/dev/null || echo "!! cuda libs skipped"

echo "==> Pre-download models (comic-text-detector + Real-ESRGAN anime)"
python - <<'PY' || true
from imagebot import enhance
enhance._ensure_weight("comictextdetector.pt.onnx", enhance.COMIC_TEXT_URLS)
enhance._ensure_weight("RealESRGAN_x4plus_anime_6B.pth", enhance.REALESRGAN_URLS)
PY

echo "==> CJK font for Japanese subtitles"
python scripts/fetch_fonts.py || true

echo "==> Capabilities detected:"
python - <<'PY'
from imagebot import enhance
for k, v in enhance.capabilities().items():
    print(f"   {'✓' if v else '·'} {k}")
PY

cat <<'MSG'

Done. Start the app with:
    source .venv/bin/activate
    python run.py

Notes:
  • Local Stable Diffusion art: run AUTOMATIC1111/Forge, then set
    IMAGEBOT_SD_URL=http://127.0.0.1:7860 in your .env
  • Reliable image search: add SERPAPI_KEY or GOOGLE_API_KEY+GOOGLE_CSE_ID
  • Tick "Clean watermarks (GPU/OCR)" in the UI, or pass --clean on the CLI.
MSG
