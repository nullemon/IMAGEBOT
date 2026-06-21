#!/usr/bin/env bash
# Set up IMAGEBOT with the optional local GPU/ML stack on Ubuntu + NVIDIA.
# Safe to re-run. Everything heavy is optional; the app works without it.
set -euo pipefail
cd "$(dirname "$0")/.."

CUDA="${CUDA:-cu121}"   # override: CUDA=cu124 bash scripts/setup_local.sh

echo "==> Python venv"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip wheel

echo "==> Core requirements"
pip install -r requirements.txt

echo "==> CUDA PyTorch ($CUDA) — edit CUDA= if your driver differs"
pip install torch torchvision --index-url "https://download.pytorch.org/whl/${CUDA}" || \
  echo "!! torch install failed — install the right build from https://pytorch.org/get-started/locally/"

echo "==> Optional GPU stack (cutout / OCR / upscale / inpaint)"
pip install -r requirements-local.txt || echo "!! some local extras failed — they're optional"

echo "==> Optional: a CJK font for Japanese subtitles"
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

Tips:
  • Local Stable Diffusion art: run AUTOMATIC1111/Forge, then set
    IMAGEBOT_SD_URL=http://127.0.0.1:7860 in your .env
  • Reliable image search: add SERPAPI_KEY or GOOGLE_API_KEY+GOOGLE_CSE_ID
MSG
