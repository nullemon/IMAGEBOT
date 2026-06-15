"""Provider base class + shared helpers."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Raised when a provider is misconfigured or its SDK is missing."""


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

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} name={self.name!r}>"
