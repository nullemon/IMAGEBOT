"""OpenAI (ChatGPT) provider — also powers Grok via the OpenAI-compatible API.

Grok/xAI exposes an OpenAI-compatible endpoint, so the same client works with a
different base_url (see GrokProvider, which subclasses this).
"""
from __future__ import annotations

import base64

from .base import (TextProvider, ProviderError, extract_json,
                   img_media_type, parse_index, PICK_INSTRUCTION)


class OpenAIProvider(TextProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini",
                 image_model: str = "gpt-image-1", base_url: str | None = None):
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise ProviderError("Run: pip install openai") from e
        self.model = model
        self.image_model = image_model
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    def complete_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        r = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (r.choices[0].message.content or "").strip()

    def complete_json(self, system: str, user: str, schema: dict):
        try:
            r = self._client.chat.completions.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": schema, "strict": False},
                },
            )
            return extract_json(r.choices[0].message.content or "")
        except Exception:
            text = self.complete_text(
                system + "\n\nReply with ONLY valid JSON. No prose, no code fences.",
                user, max_tokens=4096)
            return extract_json(text)

    def pick_image(self, images, instruction=PICK_INSTRUCTION):
        try:
            content = [{"type": "text", "text": instruction}]
            for i, data in enumerate(images):
                b64 = base64.b64encode(data).decode()
                content.append({"type": "text", "text": f"Image {i}:"})
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{img_media_type(data)};base64,{b64}"}})
            r = self._client.chat.completions.create(
                model=self.model, max_tokens=16,
                messages=[{"role": "user", "content": content}])
            return parse_index(r.choices[0].message.content or "", len(images))
        except Exception:
            return None

    def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes | None:
        try:
            r = self._client.images.generate(model=self.image_model, prompt=prompt, size=size)
            b64 = r.data[0].b64_json
            if b64:
                return base64.b64decode(b64)
            # some models/endpoints return a URL instead
            url = getattr(r.data[0], "url", None)
            if url:
                import requests
                return requests.get(url, timeout=30).content
        except Exception:
            return None
        return None


class GrokProvider(OpenAIProvider):
    """Grok (xAI) — OpenAI-compatible API at https://api.x.ai/v1."""
    name = "grok"

    def __init__(self, api_key: str, model: str = "grok-2-latest",
                 image_model: str = "grok-2-image"):
        super().__init__(api_key=api_key, model=model, image_model=image_model,
                         base_url="https://api.x.ai/v1")
