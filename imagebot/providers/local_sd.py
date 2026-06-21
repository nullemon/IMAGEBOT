"""Local Stable Diffusion image provider (uses your GPU, no API cost).

Talks to an AUTOMATIC1111 / Forge style HTTP API (``/sdapi/v1/txt2img``), which
is the most common local setup. Point IMAGEBOT_SD_URL at it, e.g.:

    IMAGEBOT_SD_URL=http://127.0.0.1:7860

Image-only: text methods are unused (raise), it just generates art.
"""
from __future__ import annotations

import base64

import requests

from .base import TextProvider, ProviderError

ANIME_NEG = ("text, watermark, signature, logo, ui, blurry, lowres, jpeg "
             "artifacts, extra limbs, bad anatomy, deformed, worst quality")


class LocalSDProvider(TextProvider):
    name = "local_sd"

    def __init__(self, url: str, model: str = ""):
        if not url:
            raise ProviderError("IMAGEBOT_SD_URL is not set")
        self.url = url.rstrip("/")
        self.model = model

    def complete_text(self, system, user, max_tokens=1024):
        raise ProviderError("local_sd is image-only")

    def complete_json(self, system, user, schema):
        raise ProviderError("local_sd is image-only")

    def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes | None:
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except Exception:
            w, h = 1024, 1024
        payload = {
            "prompt": prompt + ", anime key visual, official art, masterpiece, "
                               "best quality, highly detailed, dramatic lighting",
            "negative_prompt": ANIME_NEG,
            "width": w, "height": h,
            "steps": 28, "cfg_scale": 6.5, "sampler_name": "DPM++ 2M Karras",
        }
        if self.model:
            payload["override_settings"] = {"sd_model_checkpoint": self.model}
        try:
            r = requests.post(f"{self.url}/sdapi/v1/txt2img", json=payload, timeout=180)
            r.raise_for_status()
            imgs = r.json().get("images") or []
            if imgs:
                return base64.b64decode(imgs[0].split(",", 1)[-1])
        except Exception:
            return None
        return None
