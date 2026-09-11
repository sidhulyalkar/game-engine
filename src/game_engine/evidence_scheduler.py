from __future__ import annotations

from dataclasses import dataclass

from .evidence_contract import EvidenceLedger
from .promotion_policy import GENERATED_CRITIC_ELIGIBLE, FINAL_PLAYER_PROMOTION


@dataclass(frozen=True, slots=True)
class EvidenceAction:
    action: str
    scope: str | None
    reason: str
    spend_class: str
    terminal: bool = False


# Ordered by cost and causal dependency. A later evaluator is never purchased while
# an earlier capability is failed, incomplete, or unmeasured.
_GENERATED_ORDER = (
    "source_semantics",
    "reference_browser",
    "causal_controls",
    "restart_integrity",
    "independent_pixels",
    "cross_browser",
    "critic_quorum",
    "human_fun",
)


def _failed_action(scope: str) -> EvidenceAction:
    if scope == "source_semantics":
        return EvidenceAction("repair_source_contract", scope, "deterministic source contract failed", "bounded_llm")
    if scope == "reference_browser":
        return EvidenceAction("repair_reference_browser", scope, "candidate does not execute in the reference browser", "bounded_llm")
    if scope in {"causal_controls", "restart_integrity", "independent_pixels"}:
        return EvidenceAction("repair_behavior", scope, f"causal gameplay capability failed: {scope}", "bounded_llm")
    if scope == "cross_browser":
        return EvidenceAction("repair_cross_browser", scope, "behaviorally valid candidate is not portable across target browsers", "bounded_llm")
    if scope == "critic_quorum":
        return EvidenceAction("halt_critic_rejection", scope, "independent critic evidence explicitly failed", "none", terminal=True)
    if scope == "human_fun":
        return EvidenceAction("halt_player_rejection", scope, "player-facing evidence rejected the candidate", "none", terminal=True)
    raise ValueError(f"unsupported failed scope: {scope}")


def _incomplete_action(scope: str) -> EvidenceAction:
    if scope == "source_semantics":
        return EvidenceAction("rerun_source_evidence", scope, "source evaluator evidence is incomplete", "deterministic")
    if scope == "reference_browser":
        return EvidenceAction("rerun_reference_browser", scope, "reference-browser evidence is incomplete", "browser_reference")
    if scope in {"causal_controls", "restart_integrity", "independent_pixels"}:
        return EvidenceAction("rerun_behavior_evidence", scope, f"behavior probe evidence is incomplete: {scope}", "browser_reference")
    if scope == "cross_browser":
        return EvidenceAction("rerun_cross_browser", scope, "compatibility evidence is incomplete", "browser_promotion")
    if scope == "critic_quorum":
        return EvidenceAction("rerun_independent_critics", scope, "critic quorum is incomplete", "llm_critics")
    if scope == "human_fun":
        return EvidenceAction("collect_human_playtest", scope, "player-facing preference evidence is incomplete", "human")
    raise ValueError(f"unsupported incomplete scope: {scope}")


def _missing_action(scope: str) -> EvidenceAction:
    if scope == "source_semantics":
        return EvidenceAction("run_source_evidence", scope, "no deterministic source evidence exists", "deterministic")
    if scope == "reference_browser":
        return EvidenceAction("run_reference_browser", scope, "source-qualified candidate has not executed in a reference browser", "browser_reference")
    if scope in {"causal_controls", "restart_integrity", "independent_pixels"}:
        return EvidenceAction("run_behavior_evidence", scope, "reference-browser candidate lacks causal gameplay evidence", "browser_reference")
    if scope == "cross_browser":
        return EvidenceAction("run_cross_browser", scope, "behaviorally qualified candidate has not earned compatibility evidence", "browser_promotion")
    if scope == "critic_quorum":
        return EvidenceAction("run_independent_critics", scope, "objective evidence is complete; subjective critic quorum is next", "llm_critics")
    if scope == "human_fun":
        return EvidenceAction("collect_human_playtest", scope, "automated evidence is complete; human preference remains unmeasured", "human")
    raise ValueError(f"unsupported missing scope: {scope}")


def next_generated_action(ledger: EvidenceLedger) -> EvidenceAction:
    """Return exactly one cheapest legitimate next action for a generated game lineage."""
    # Failures and incomplete measurements take precedence over missing later stages.
    for scope in _GENERATED_ORDER:
        state = ledger.state(scope)
        if state == "failed":
            return _failed_action(scope)
        if state == "incomplete":
            return _incomplete_action(scope)
        if state == "not_evaluated":
            return _missing_action(scope)

    if ledger.qualified(FINAL_PLAYER_PROMOTION):
        return EvidenceAction(
            "promotion_eligible",
            None,
            "all automated, critic, and player-facing evidence scopes are qualified",
            "none",
            terminal=True,
        )

    # This should be unreachable because FINAL_PLAYER_PROMOTION is the generated
    # evidence order, but fail closed if policies diverge in a future refactor.
    missing = [scope for scope in GENERATED_CRITIC_ELIGIBLE if ledger.state(scope) != "qualified"]
    return EvidenceAction(
        "halt_policy_inconsistency",
        None,
        f"evidence policy and scheduler order diverged: {missing}",
        "none",
        terminal=True,
    )
