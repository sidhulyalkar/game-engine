from game_engine.evidence_contract import (
    EvidenceClaim,
    EvidenceLedger,
    claims_from_staged_evidence,
    claims_from_template_report,
    critic_quorum_claim,
    regression_claim,
    replay_claim,
)


def test_template_pass_does_not_inherit_browser_or_fun_claims():
    claims = claims_from_template_report({
        "status": "passed_checks",
        "scope": "Instrumented deterministic scenario only; no claim of fun or rendering.",
    })
    ledger = EvidenceLedger("puma-world-0", "template", claims)
    assert ledger.state("instrumented_simulation") == "qualified"
    assert ledger.state("reference_browser") == "not_evaluated"
    assert ledger.state("cross_browser") == "not_evaluated"
    assert ledger.state("human_fun") == "not_evaluated"


def test_staged_web_pass_does_not_inherit_template_replay_or_fun():
    claims = claims_from_staged_evidence({
        "semantic_qualified_build_ids": ["game"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["game"],
        "behaviorally_qualified_build_ids": ["game"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": ["game"],
    }, "game")
    ledger = EvidenceLedger("game", "generated", claims)
    for scope in (
        "source_semantics", "reference_browser", "causal_controls",
        "restart_integrity", "independent_pixels", "cross_browser",
    ):
        assert ledger.state(scope) == "qualified"
    assert ledger.state("instrumented_simulation") == "not_evaluated"
    assert ledger.state("exact_replay") == "not_evaluated"
    assert ledger.state("human_fun") == "not_evaluated"


def test_behavioral_repair_candidate_is_failed_not_qualified():
    claims = claims_from_staged_evidence({
        "semantic_qualified_build_ids": ["game"],
        "reference_browser_build_ids": ["game"],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": ["game"],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": False,
        "cross_browser_build_ids": [],
    }, "game")
    ledger = EvidenceLedger("game", "generated", claims)
    assert ledger.state("source_semantics") == "qualified"
    assert ledger.state("reference_browser") == "qualified"
    assert ledger.state("causal_controls") == "failed"
    assert ledger.state("restart_integrity") == "failed"
    assert ledger.state("independent_pixels") == "failed"
    assert ledger.state("cross_browser") == "not_evaluated"


def test_incomplete_claim_prevents_positive_claim_from_silently_certifying_scope():
    ledger = EvidenceLedger("x", "lineage", [
        EvidenceClaim("causal_controls", "qualified", "probe-a"),
        EvidenceClaim("causal_controls", "incomplete", "probe-b"),
    ])
    assert ledger.state("causal_controls") == "incomplete"
    assert not ledger.qualified(["causal_controls"])


def test_failure_dominates_all_other_claim_states():
    ledger = EvidenceLedger("x", "lineage", [
        EvidenceClaim("cross_browser", "qualified", "old-run"),
        EvidenceClaim("cross_browser", "incomplete", "partial-run"),
        EvidenceClaim("cross_browser", "failed", "new-run"),
    ])
    assert ledger.state("cross_browser") == "failed"


def test_replay_regression_and_critic_claims_remain_independent():
    ledger = EvidenceLedger("template", "template", [
        replay_claim(True),
        regression_claim(False),
        critic_quorum_claim(1),
    ])
    assert ledger.state("exact_replay") == "qualified"
    assert ledger.state("template_regressions") == "failed"
    assert ledger.state("critic_quorum") == "incomplete"
    assert ledger.state("human_fun") == "not_evaluated"


def test_critic_quorum_requires_two_independent_successes():
    assert critic_quorum_claim(0).state == "incomplete"
    assert critic_quorum_claim(1).state == "incomplete"
    assert critic_quorum_claim(2).state == "qualified"
    assert critic_quorum_claim(5).state == "qualified"
