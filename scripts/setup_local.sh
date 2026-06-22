#!/usr/bin/env bash
# Set up IMAGEBOT with the optional local GPU/ML stack on Ubuntu + NVIDIA.
# No sudo required: if python3-venv is missing it falls back to `uv`
# (installed to ~/.local, which creates the venv + Python itself).
# Safe to re-run. Everything heavy is optional; the app works without it.
set -euo pipefail
cd "$(dirname "$0")/.."

CUDA="${CUDA:-cu121}"   # override: CUDA=cu124 bash scripts/setup_local.sh

# --- make a virtualenv without sudo --------------------------------------
USE_UV=0
if python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "==> Python venv (stdlib)"
  python3 -m venv .venv
else
  echo "==> python3-venv missing -> using uv (no sudo needed)"
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "!! couldn't install uv. Either install it from https://docs.astral.sh/uv/"
    echo "   or ask an admin for: sudo apt install -y python3-venv python3-pip"
    exit 1
  fi
  uv venv .venv --python 3.12 || uv venv .venv
  USE_UV=1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pipi() { if [ "$USE_UV" = 1 ]; then uv pip install "$@"; else pip install "$@"; fi; }
if [ "$USE_UV" = 0 ]; then pip install -U pip wheel; else uv pip install wheel; fi

echo "==> Core requirements"
pipi -r requirements.txt

echo "==> CUDA PyTorch ($CUDA) — edit CUDA= if your driver differs"
pipi torch torchvision --index-url "https://download.pytorch.org/whl/${CUDA}" || \
  echo "!! torch install failed — install the right build from https://pytorch.org/get-started/locally/"

echo "==> Optional GPU stack (rembg / onnxruntime-gpu / lama / spandrel / manga-ocr)"
pipi -r requirements-local.txt || echo "!! some local extras failed — they're optional"

echo "==> CRAFT text detector (no-deps: its setup pins an ancient opencv)"
pipi --no-deps craft-text-detector || echo "!! craft-text-detector skipped (comic-text-detector still works)"

echo "==> CUDA 12 runtime libs for onnxruntime-gpu"
pipi nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 nvidia-cudnn-cu12 \
    nvidia-cufft-cu12 nvidia-curand-cu12 2>/dev/null || echo "!! cuda libs skipped"

echo "==> Pre-download all models into ./models (self-contained, separate to this bot)"
python - <<'PY' || true
from PIL import Image
from imagebot import enhance
enhance._ensure_weight("comictextdetector.pt.onnx", enhance.COMIC_TEXT_URLS)
enhance._ensure_weight("RealESRGAN_x4plus_anime_6B.pth", enhance.REALESRGAN_URLS)
try:                       # pulls the rembg cut-out model into ./models/rembg
    enhance.remove_background(Image.new("RGB", (64, 64), (180, 80, 60)))
except Exception:
    pass
import os
print("models/:", sorted(os.listdir("models")) if os.path.isdir("models") else "(none)")
PY

echo "==> CJK font for Japanese subtitles"
python scripts/fetch_fonts.py || true

echo "==> Capabilities detected:"
python - <<'PY'
from imagebot import enhance
for k, v in enhance.capabilities().items():
    print(f"   {'OK ' if v else ' . '} {k}")
PY

cat <<'MSG'

Done. Start the app with:
    source .venv/bin/activate
    python run.py                 # http://127.0.0.1:8777

Tips:
  - Port auto-picks a free one if 8777 is busy. WSL/LAN: python run.py --host 0.0.0.0
  - Local Stable Diffusion art: run AUTOMATIC1111/Forge, then set
    IMAGEBOT_SD_URL=http://127.0.0.1:7860 in your .env
  - Reliable image search: add SERPAPI_KEY or GOOGLE_API_KEY+GOOGLE_CSE_ID
MSG
