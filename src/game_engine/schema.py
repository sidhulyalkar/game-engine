from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Brief:
    theme: str
    # Legacy mirror retained for artifact/backward compatibility. New briefs should
    # declare one primary category and optional expansion lanes.
    target_categories: list[str] = field(default_factory=lambda: ["desktop"])
    primary_category: str | None = None
    expansion_categories: list[str] = field(default_factory=list)
    native_hybrid: bool = False
    size_limit_bytes: int = 13 * 1024
    desired_session_seconds: int = 180
    audience: str = "players who value immediate, replayable browser games"
    must_have: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    creative_direction: str = "surprising mechanics with readable controls and strong game feel"

    def __post_init__(self) -> None:
        categories = [str(value).lower() for value in self.target_categories if str(value).strip()]
        if not categories:
            categories = ["desktop"]
        if self.primary_category is None:
            self.primary_category = categories[0]
        self.primary_category = str(self.primary_category).lower()

        if not self.expansion_categories:
            self.expansion_categories = [value for value in categories if value != self.primary_category]
        else:
            self.expansion_categories = [
                str(value).lower()
                for value in self.expansion_categories
                if str(value).strip() and str(value).lower() != self.primary_category
            ]

        # Keep the old field as a stable all-intents mirror for artifacts/readers.
        self.target_categories = list(dict.fromkeys([self.primary_category, *self.expansion_categories]))

    @property
    def active_categories(self) -> list[str]:
        """Categories allowed to shape the current core search."""
        if self.native_hybrid:
            return list(self.target_categories)
        return [self.primary_category or "desktop"]

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


@dataclass(slots=True)
class GameSpec:
    """A small executable contract between game design and implementation."""

    spec_version: str
    source_concept_id: str
    title: str
    primary_category: str
    interaction_invariant: str
    player_goal: str
    controls: str
    core_loop: list[str]
    prototype_scope: list[str]
    state_machine: dict[str, Any]
    timing_contract: dict[str, Any]
    state_bounds: dict[str, int]
    sensory_contract: dict[str, str]
    telemetry_contract: dict[str, list[str]]
    byte_priorities: list[str]
    non_goals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
