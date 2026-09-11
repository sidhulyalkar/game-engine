from game_engine.evidence_contract import EvidenceClaim, EvidenceLedger
from game_engine.promotion_policy import (
    FINAL_PLAYER_PROMOTION,
    GENERATED_CRITIC_ELIGIBLE,
    TEMPLATE_REPLAY_ELIGIBLE,
    evaluate_promotion,
)


def ledger_with(scopes, *, subject="x", lineage="generated"):
    return EvidenceLedger(
        subject,
        lineage,
        [EvidenceClaim(scope, "qualified", "fixture") for scope in scopes],
    )


def test_generated_candidate_needs_every_objective_scope_before_critic_spend():
    ledger = ledger_with(GENERATED_CRITIC_ELIGIBLE)
    decision = evaluate_promotion(ledger, GENERATED_CRITIC_ELIGIBLE)
    assert decision.eligible
    assert decision.missing_scopes == ()


def test_missing_cross_browser_blocks_generated_critic_eligibility():
    ledger = ledger_with(scope for scope in GENERATED_CRITIC_ELIGIBLE if scope != "cross_browser")
    decision = evaluate_promotion(ledger, GENERATED_CRITIC_ELIGIBLE)
    assert decision.status == "blocked_missing_evidence"
    assert decision.missing_scopes == ("cross_browser",)


def test_observed_failure_dominates_missing_and_incomplete_for_promotion():
    ledger = EvidenceLedger("x", "generated", [
        EvidenceClaim("source_semantics", "qualified", "static"),
        EvidenceClaim("reference_browser", "qualified", "chromium"),
        EvidenceClaim("causal_controls", "failed", "m4"),
        EvidenceClaim("restart_integrity", "incomplete", "m4"),
    ])
    decision = evaluate_promotion(ledger, GENERATED_CRITIC_ELIGIBLE)
    assert decision.status == "blocked_failure"
    assert decision.failed_scopes == ("causal_controls",)
    assert decision.incomplete_scopes == ("restart_integrity",)
    assert "cross_browser" in decision.missing_scopes


def test_template_replay_policy_does_not_require_browser_or_fun():
    ledger = ledger_with(TEMPLATE_REPLAY_ELIGIBLE, lineage="template")
    decision = evaluate_promotion(ledger, TEMPLATE_REPLAY_ELIGIBLE)
    assert decision.eligible


def test_template_pass_cannot_be_reused_as_generated_critic_evidence():
    ledger = ledger_with(TEMPLATE_REPLAY_ELIGIBLE, lineage="template")
    decision = evaluate_promotion(ledger, GENERATED_CRITIC_ELIGIBLE)
    assert decision.status == "blocked_missing_evidence"
    assert set(decision.missing_scopes) == set(GENERATED_CRITIC_ELIGIBLE)


def test_automated_generated_evidence_can_never_claim_final_player_promotion_without_human_fun():
    automated = (*GENERATED_CRITIC_ELIGIBLE, "critic_quorum")
    ledger = ledger_with(automated)
    decision = evaluate_promotion(ledger, FINAL_PLAYER_PROMOTION)
    assert decision.status == "blocked_missing_evidence"
    assert decision.missing_scopes == ("human_fun",)


def test_human_fun_failure_blocks_even_when_every_automated_gate_passes():
    claims = [EvidenceClaim(scope, "qualified", "fixture") for scope in FINAL_PLAYER_PROMOTION if scope != "human_fun"]
    claims.append(EvidenceClaim("human_fun", "failed", "blind-player-test"))
    decision = evaluate_promotion(EvidenceLedger("x", "generated", claims), FINAL_PLAYER_PROMOTION)
    assert decision.status == "blocked_failure"
    assert decision.failed_scopes == ("human_fun",)
