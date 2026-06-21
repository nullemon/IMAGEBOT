"""Claude (Anthropic) provider — uses the official `anthropic` SDK."""
from __future__ import annotations

import base64

from .base import (TextProvider, ProviderError, extract_json,
                   img_media_type, parse_index, PICK_INSTRUCTION)


class AnthropicProvider(TextProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-opus-4-8"):
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise ProviderError("Run: pip install anthropic") from e
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        r = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if b.type == "text").strip()

    def complete_json(self, system: str, user: str, schema: dict):
        # Preferred path: native structured outputs (Opus 4.8 / Sonnet 4.6 / Haiku 4.5).
        try:
            r = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            text = next(b.text for b in r.content if b.type == "text")
            return extract_json(text)
        except Exception:
            # Fallback: ask for JSON in the prompt and parse leniently.
            text = self.complete_text(
                system + "\n\nReply with ONLY valid JSON. No prose, no code fences.",
                user,
                max_tokens=4096,
            )
            return extract_json(text)

    def pick_image(self, images, instruction=PICK_INSTRUCTION):
        try:
            content = [{"type": "text", "text": instruction}]
            for i, data in enumerate(images):
                content.append({"type": "text", "text": f"Image {i}:"})
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": img_media_type(data),
                    "data": base64.b64encode(data).decode()}})
            r = self._client.messages.create(
                model=self.model, max_tokens=16,
                messages=[{"role": "user", "content": content}])
            text = "".join(b.text for b in r.content if b.type == "text")
            return parse_index(text, len(images))
        except Exception:
            return None
