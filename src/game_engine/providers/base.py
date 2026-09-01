from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> str:
        """Return model text for one studio assignment."""
