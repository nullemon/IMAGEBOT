"""Pluggable AI providers (Claude, OpenAI, Gemini, Grok).

Each provider exposes a small uniform surface used by the pipeline:
  - complete_text(system, user)   -> str
  - complete_json(system, user, schema) -> dict | list
  - generate_image(prompt)        -> bytes | None   (optional)

Providers are constructed via `get_text_provider()` / `get_image_provider()`
from config, and import their SDK lazily so unused providers need no install.
"""
from .base import TextProvider, ProviderError
from .registry import (
    get_text_provider,
    get_image_provider,
    build_provider,
    PROVIDERS,
)

__all__ = [
    "TextProvider",
    "ProviderError",
    "get_text_provider",
    "get_image_provider",
    "build_provider",
    "PROVIDERS",
]
