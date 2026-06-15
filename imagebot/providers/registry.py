"""Build providers from settings, and resolve which one to use."""
from __future__ import annotations

from .base import TextProvider, ProviderError

PROVIDERS = ("claude", "openai", "gemini", "grok")

# Providers capable of image *generation* (for the optional AI-art fallback).
IMAGE_CAPABLE = ("openai", "gemini", "grok")


def build_provider(name: str, settings) -> TextProvider:
    name = (name or "").lower()
    if name == "claude":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(settings.anthropic_key, settings.anthropic_model)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(settings.openai_key, settings.openai_model,
                              settings.openai_image_model)
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(settings.gemini_key, settings.gemini_model,
                              settings.gemini_image_model)
    if name == "grok":
        from .openai_provider import GrokProvider
        return GrokProvider(settings.xai_key, settings.xai_model, settings.xai_image_model)
    raise ProviderError(f"unknown provider: {name!r}")


def get_text_provider(settings, name: str | None = None) -> TextProvider | None:
    """Return a text provider, or None if none is configured/available."""
    chosen = (name or settings.resolve_text_provider())
    if chosen in (None, "", "none"):
        return None
    try:
        return build_provider(chosen, settings)
    except ProviderError:
        return None


def get_image_provider(settings, name: str | None = None) -> TextProvider | None:
    """Return a provider that can generate images, preferring `name`."""
    order = []
    if name:
        order.append(name.lower())
    # then any configured image-capable provider
    avail = settings.available_text_providers()
    order += [p for p in IMAGE_CAPABLE if p in avail]
    seen = set()
    for p in order:
        if p in seen or p not in IMAGE_CAPABLE:
            continue
        seen.add(p)
        try:
            return build_provider(p, settings)
        except ProviderError:
            continue
    return None
