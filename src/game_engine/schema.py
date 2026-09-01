from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Brief:
    theme: str
    target_categories: list[str] = field(default_factory=lambda: ["desktop"])
    size_limit_bytes: int = 13 * 1024
    desired_session_seconds: int = 180
    audience: str = "players who value immediate, replayable browser games"
    must_have: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    creative_direction: str = "surprising mechanics with readable controls and strong game feel"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Brief":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Concept:
    concept_id: str
    title: str
    hook: str
    core_mechanic: str
    player_goal: str
    controls: str
    core_loop: list[str]
    escalation: list[str]
    visual_grammar: str
    audio_grammar: str
    category_fit: list[str]
    byte_hypothesis: str
    risks: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Concept":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreCard:
    concept_id: str
    scores: dict[str, float]
    total: float
    strengths: list[str]
    weaknesses: list[str]
    mutation_requests: list[str]
    vetoes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
