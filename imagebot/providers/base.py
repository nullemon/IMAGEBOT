"""Provider base class + shared helpers."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Raised when a provider is misconfigured or its SDK is missing."""


def img_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def parse_index(text: str, n: int) -> int | None:
    m = re.search(r"\d+", text or "")
    if m:
        i = int(m.group())
        if 0 <= i < n:
            return i
    return None


PICK_INSTRUCTION = (
    "You are choosing the best image to use as the background of an anime news "
    "banner. Pick the cleanest official key visual / character art: sharp and "
    "high quality, on-model, a strong single subject, minimal embedded text, "
    "watermarks or UI, and good for a wide banner crop. "
    "Reply with ONLY the 0-based index number of the best image.")


def extract_json(text: str):
    """Best-effort: pull the first JSON object/array out of a model reply.

    Used as a fallback when a provider can't enforce a JSON schema natively.
    """
    if not text:
        raise ValueError("empty response")
    text = text.strip()
    # strip ```json fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # find the outermost {...} or [...]
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                continue
    raise ValueError(f"could not parse JSON from response: {text[:200]}")


class TextProvider(ABC):
    """A text/vision provider. Image generation is optional (returns None)."""

    name: str = "base"

    @abstractmethod
    def complete_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        ...

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict):
        ...

    def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes | None:
        """Generate an image; None if this provider can't."""
        return None

    def pick_image(self, images: list[bytes], instruction: str = PICK_INSTRUCTION) -> int | None:
        """Vision: choose the best candidate image. None if unsupported/failed."""
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} name={self.name!r}>"
