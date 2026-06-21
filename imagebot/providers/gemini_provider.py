"""Google Gemini provider — uses the `google-genai` SDK."""
from __future__ import annotations

from .base import (TextProvider, ProviderError, extract_json,
                   img_media_type, parse_index, PICK_INSTRUCTION)


class GeminiProvider(TextProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 image_model: str = "imagen-3.0-generate-002"):
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        try:
            from google import genai  # google-genai
        except ImportError as e:  # pragma: no cover
            raise ProviderError("Run: pip install google-genai") from e
        self._genai = genai
        self.model = model
        self.image_model = image_model
        self._client = genai.Client(api_key=api_key)

    def complete_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        from google.genai import types
        r = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return (r.text or "").strip()

    def complete_json(self, system: str, user: str, schema: dict):
        from google.genai import types
        r = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system + "\n\nReply with ONLY valid JSON matching the requested shape.",
                response_mime_type="application/json",
                max_output_tokens=4096,
            ),
        )
        return extract_json(r.text or "")

    def pick_image(self, images, instruction=PICK_INSTRUCTION):
        try:
            from google.genai import types
            parts = [instruction]
            for i, data in enumerate(images):
                parts.append(f"Image {i}:")
                parts.append(types.Part.from_bytes(data=data, mime_type=img_media_type(data)))
            r = self._client.models.generate_content(model=self.model, contents=parts)
            return parse_index(r.text or "", len(images))
        except Exception:
            return None

    def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes | None:
        try:
            r = self._client.models.generate_images(model=self.image_model, prompt=prompt)
            imgs = getattr(r, "generated_images", None) or []
            if imgs:
                return imgs[0].image.image_bytes
        except Exception:
            return None
        return None
