"""Configuration: API keys from .env, branding/themes from config.yaml.

Everything has a default so the app runs with no .env and no config.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .models import BrandConfig, CardSpec

ROOT = Path(__file__).resolve().parent.parent

# Load .env if present (no-op if python-dotenv isn't installed).
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv optional
    pass

DEFAULT_THEMES = {
    "gold": {"top": "#3a2a12", "bottom": "#7a5a22", "accent": "#F5A623"},
    "navy": {"top": "#0b1a2e", "bottom": "#16395e", "accent": "#3FA7FF"},
    "crimson": {"top": "#2a0b10", "bottom": "#7a1422", "accent": "#FF4D5E"},
    "violet": {"top": "#1c0f2e", "bottom": "#43286e", "accent": "#B07CFF"},
    "forest": {"top": "#0e2018", "bottom": "#1f4a33", "accent": "#48D08A"},
    "slate": {"top": "#14181d", "bottom": "#2b333d", "accent": "#9AA7B4"},
}


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass
class Settings:
    # text provider
    text_provider: str = "auto"
    # provider keys / models
    anthropic_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openai_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_image_model: str = "gpt-image-1"
    gemini_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "imagen-3.0-generate-002"
    xai_key: str = ""
    xai_model: str = "grok-2-latest"
    xai_image_model: str = "grok-2-image"
    # local Stable Diffusion (AUTOMATIC1111 / Forge / ComfyUI-compatible)
    sd_url: str = ""
    sd_model: str = ""
    # image search
    serpapi_key: str = ""
    google_api_key: str = ""
    google_cse_id: str = ""
    # output / server
    output_dir: str = "output"
    host: str = "127.0.0.1"
    port: int = 8777
    # branding + layout
    brand: BrandConfig = field(default_factory=BrandConfig)
    themes: dict = field(default_factory=lambda: dict(DEFAULT_THEMES))
    accounts: list = field(default_factory=list)   # [{name, handle, watermark, event_name, event_badge, accent}]
    card_width: int = 1080
    card_height: int = 1350
    panels_per_card: int = 4
    divider: bool = True

    # ---- providers available (have a key) -------------------------------
    def available_text_providers(self) -> list[str]:
        out = []
        if self.anthropic_key:
            out.append("claude")
        if self.openai_key:
            out.append("openai")
        if self.gemini_key:
            out.append("gemini")
        if self.xai_key:
            out.append("grok")
        return out

    def resolve_text_provider(self) -> str:
        """Return the provider to use for text, or 'none' if no key set."""
        avail = self.available_text_providers()
        if self.text_provider in avail:
            return self.text_provider
        if self.text_provider == "auto" and avail:
            return avail[0]
        if self.text_provider not in ("auto", "none") and not avail:
            return "none"
        return avail[0] if avail else "none"

    def card_spec(self, **overrides) -> CardSpec:
        spec = CardSpec(
            width=self.card_width,
            height=self.card_height,
            panels_per_card=self.panels_per_card,
            divider=self.divider,
            brand=replace(self.brand),     # a fresh copy so per-account edits don't leak
            themes=self.themes,
        )
        for k, v in overrides.items():
            if v is not None and hasattr(spec, k):
                setattr(spec, k, v)
        return spec


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def load_settings() -> Settings:
    s = Settings(
        text_provider=_env("IMAGEBOT_TEXT_PROVIDER", "auto").lower(),
        anthropic_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-4-8"),
        openai_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL", "gpt-4o-mini"),
        openai_image_model=_env("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        gemini_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.0-flash"),
        gemini_image_model=_env("GEMINI_IMAGE_MODEL", "imagen-3.0-generate-002"),
        xai_key=_env("XAI_API_KEY"),
        xai_model=_env("XAI_MODEL", "grok-2-latest"),
        xai_image_model=_env("XAI_IMAGE_MODEL", "grok-2-image"),
        sd_url=_env("IMAGEBOT_SD_URL"),
        sd_model=_env("IMAGEBOT_SD_MODEL"),
        serpapi_key=_env("SERPAPI_KEY"),
        google_api_key=_env("GOOGLE_API_KEY"),
        google_cse_id=_env("GOOGLE_CSE_ID"),
        output_dir=_env("IMAGEBOT_OUTPUT_DIR", "output"),
        host=_env("IMAGEBOT_HOST", "127.0.0.1"),
        port=int(_env("IMAGEBOT_PORT", "8777") or "8777"),
    )

    # Merge config.yaml (or config.example.yaml as a starting fallback).
    cfg = _load_yaml(ROOT / "config.yaml") or _load_yaml(ROOT / "config.example.yaml")
    brand = cfg.get("brand", {}) if isinstance(cfg, dict) else {}
    if brand:
        s.brand = BrandConfig(
            event_name=brand.get("event_name", s.brand.event_name),
            event_badge=brand.get("event_badge", s.brand.event_badge),
            watermark=brand.get("watermark", s.brand.watermark),
            accent=brand.get("accent", s.brand.accent),
            default_tag_sub=brand.get("default_tag_sub", s.brand.default_tag_sub),
        )
    card = cfg.get("card", {}) if isinstance(cfg, dict) else {}
    s.card_width = int(card.get("width", s.card_width))
    s.card_height = int(card.get("height", s.card_height))
    s.panels_per_card = int(card.get("panels_per_card", s.panels_per_card))
    s.divider = bool(card.get("divider", s.divider))
    if isinstance(cfg, dict) and cfg.get("themes"):
        s.themes = {**DEFAULT_THEMES, **cfg["themes"]}
    if isinstance(cfg, dict) and isinstance(cfg.get("accounts"), list):
        s.accounts = cfg["accounts"]

    return s


# Singleton-ish accessor
_SETTINGS: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _SETTINGS
    if _SETTINGS is None or reload:
        _SETTINGS = load_settings()
    return _SETTINGS
