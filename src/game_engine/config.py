from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .providers import OpenAICompatibleClient


@dataclass(slots=True)
class ProviderSpec:
    name: str
    model: str
    base_url: str
    api_key_env: str
    roles: list[str]
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict) -> "ProviderSpec":
        return cls(**value)


def load_provider_specs(path: Path) -> list[ProviderSpec]:
    raw = json.loads(path.read_text())
    return [ProviderSpec.from_dict(item) for item in raw.get("providers", []) if item.get("enabled", True)]


def build_clients(specs: list[ProviderSpec]) -> list[tuple[ProviderSpec, OpenAICompatibleClient]]:
    return [
        (spec, OpenAICompatibleClient(spec.name, spec.model, spec.base_url, spec.api_key_env))
        for spec in specs
    ]
