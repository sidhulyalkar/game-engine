from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evidence_contract import EVIDENCE_SCOPES, EvidenceLedger


GENERATED_CRITIC_ELIGIBLE = (
    "source_semantics",
    "reference_browser",
    "causal_controls",
    "restart_integrity",
    "independent_pixels",
    "cross_browser",
)

TEMPLATE_REPLAY_ELIGIBLE = (
    "instrumented_simulation",
    "exact_replay",
    "template_regressions",
)

# No current automated evaluator is authorized to produce human_fun. Keeping it in
# the final policy makes release/promotion structurally fail closed until actual
# player-facing evidence is attached.
FINAL_PLAYER_PROMOTION = (
    *GENERATED_CRITIC_ELIGIBLE,
    "critic_quorum",
    "human_fun",
)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: str
    required_scopes: tuple[str, ...]
    qualified_scopes: tuple[str, ...]
    failed_scopes: tuple[str, ...]
    incomplete_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"


def evaluate_promotion(
    ledger: EvidenceLedger,
    required_scopes: Iterable[str],
) -> PromotionDecision:
    required = tuple(dict.fromkeys(str(scope) for scope in required_scopes))
    unknown = sorted(set(required) - set(EVIDENCE_SCOPES))
    if unknown:
        raise ValueError(f"unknown promotion scopes: {unknown}")
    if not required:
        raise ValueError("promotion policy requires at least one evidence scope")

    qualified: list[str] = []
    failed: list[str] = []
    incomplete: list[str] = []
    missing: list[str] = []
    for scope in required:
        state = ledger.state(scope)
        if state == "qualified":
            qualified.append(scope)
        elif state == "failed":
            failed.append(scope)
        elif state == "incomplete":
            incomplete.append(scope)
        else:
            missing.append(scope)

    if failed:
        status = "blocked_failure"
    elif incomplete:
        status = "blocked_incomplete_evidence"
    elif missing:
        status = "blocked_missing_evidence"
    else:
        status = "eligible"

    return PromotionDecision(
        status=status,
        required_scopes=required,
        qualified_scopes=tuple(qualified),
        failed_scopes=tuple(failed),
        incomplete_scopes=tuple(incomplete),
        missing_scopes=tuple(missing),
    )
