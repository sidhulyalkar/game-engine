from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    temperature: float = 0.9
    top_p: float | None = 0.95
    max_tokens: int = 8192
    timeout: int = 180
    retries: int = 3
    max_concurrency: int = 1
    extra_body: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict) -> "ProviderSpec":
        spec = cls(**value)
        spec.validate_request_contract()
        return spec

    def validate_request_contract(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError(f"Provider {self.name} max_concurrency must be >= 1")

        # NVIDIA's hosted Kimi-K3 endpoint treats nucleus sampling as model-fixed.
        # Omit top_p (preferred) or use the currently accepted fixed value rather
        # than paying for a deterministic HTTP 400 later in a tournament.
        if self.model.lower() == "moonshotai/kimi-k3":
            if self.top_p is not None and abs(float(self.top_p) - 0.95) > 1e-9:
                raise ValueError(
                    f"Provider {self.name} model moonshotai/kimi-k3 has model-fixed top_p; "
                    "omit top_p (null) or use 0.95"
                )
            effort = self.extra_body.get("reasoning_effort")
            if effort is not None and effort not in {"low", "high", "max"}:
                raise ValueError(
                    f"Provider {self.name} model moonshotai/kimi-k3 reasoning_effort "
                    "must be one of low, high, max"
                )


def load_provider_specs(path: Path) -> list[ProviderSpec]:
    raw = json.loads(path.read_text())
    specs = [ProviderSpec.from_dict(item) for item in raw.get("providers", []) if item.get("enabled", True)]
    if not specs:
        raise ValueError(f"No enabled providers configured in {path}")
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("Provider names must be unique")
    return specs


def build_clients(specs: list[ProviderSpec]) -> list[tuple[ProviderSpec, OpenAICompatibleClient]]:
    return [
        (
            spec,
            OpenAICompatibleClient(
                spec.name,
                spec.model,
                spec.base_url,
                spec.api_key_env,
                timeout=spec.timeout,
                temperature=spec.temperature,
                top_p=spec.top_p,
                max_tokens=spec.max_tokens,
                retries=spec.retries,
                extra_body=spec.extra_body,
            ),
        )
        for spec in specs
    ]
