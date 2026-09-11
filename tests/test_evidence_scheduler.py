from game_engine.evidence_contract import EvidenceClaim, EvidenceLedger
from game_engine.evidence_scheduler import next_generated_action


def ledger(states):
    return EvidenceLedger(
        "game",
        "generated-web",
        [EvidenceClaim(scope, state, "fixture") for scope, state in states.items()],
    )


def automated_objective():
    return {
        "source_semantics": "qualified",
        "reference_browser": "qualified",
        "causal_controls": "qualified",
        "restart_integrity": "qualified",
        "independent_pixels": "qualified",
        "cross_browser": "qualified",
    }


def test_empty_lineage_starts_with_free_deterministic_source_evidence():
    action = next_generated_action(ledger({}))
    assert action.action == "run_source_evidence"
    assert action.spend_class == "deterministic"


def test_source_failure_repairs_before_any_browser_spend():
    action = next_generated_action(ledger({"source_semantics": "failed"}))
    assert action.action == "repair_source_contract"
    assert action.scope == "source_semantics"
    assert action.spend_class == "bounded_llm"


def test_source_qualified_lineage_buys_reference_browser_next():
    action = next_generated_action(ledger({"source_semantics": "qualified"}))
    assert action.action == "run_reference_browser"
    assert action.spend_class == "browser_reference"


def test_behavior_failure_never_buys_cross_browser_or_critics():
    action = next_generated_action(ledger({
        "source_semantics": "qualified",
        "reference_browser": "qualified",
        "causal_controls": "failed",
    }))
    assert action.action == "repair_behavior"
    assert action.scope == "causal_controls"
    assert action.spend_class == "bounded_llm"


def test_behavior_probe_gap_is_rerun_not_mislabeled_as_game_failure():
    action = next_generated_action(ledger({
        "source_semantics": "qualified",
        "reference_browser": "qualified",
        "causal_controls": "qualified",
        "restart_integrity": "incomplete",
    }))
    assert action.action == "rerun_behavior_evidence"
    assert action.scope == "restart_integrity"


def test_cross_browser_is_only_purchased_after_all_m4_scopes_pass():
    action = next_generated_action(ledger({
        "source_semantics": "qualified",
        "reference_browser": "qualified",
        "causal_controls": "qualified",
        "restart_integrity": "qualified",
        "independent_pixels": "qualified",
    }))
    assert action.action == "run_cross_browser"
    assert action.spend_class == "browser_promotion"


def test_critics_are_only_purchased_after_objective_generated_evidence():
    action = next_generated_action(ledger(automated_objective()))
    assert action.action == "run_independent_critics"
    assert action.spend_class == "llm_critics"


def test_incomplete_critic_quorum_retries_critics_without_replaying_browsers():
    states = automated_objective()
    states["critic_quorum"] = "incomplete"
    action = next_generated_action(ledger(states))
    assert action.action == "rerun_independent_critics"
    assert action.spend_class == "llm_critics"


def test_complete_quorum_must_materialize_verdict_before_human_testing():
    states = automated_objective()
    states["critic_quorum"] = "qualified"
    action = next_generated_action(ledger(states))
    assert action.action == "materialize_critic_resolution"
    assert action.scope == "critic_resolution"
    assert action.spend_class == "deterministic"


def test_critic_repair_verdict_routes_to_bounded_repair_not_human_test():
    states = automated_objective()
    states.update({"critic_quorum": "qualified", "critic_resolution": "repair_required"})
    action = next_generated_action(ledger(states))
    assert action.action == "repair_critic_findings"
    assert action.scope == "critic_resolution"
    assert action.spend_class == "bounded_llm"
    assert not action.terminal


def test_critic_reject_verdict_is_terminal():
    states = automated_objective()
    states.update({"critic_quorum": "qualified", "critic_resolution": "failed"})
    action = next_generated_action(ledger(states))
    assert action.action == "halt_critic_rejection"
    assert action.scope == "critic_resolution"
    assert action.terminal


def test_unrecognized_or_partial_critic_resolution_reruns_critics():
    states = automated_objective()
    states.update({"critic_quorum": "qualified", "critic_resolution": "incomplete"})
    action = next_generated_action(ledger(states))
    assert action.action == "rerun_independent_critics"
    assert action.scope == "critic_resolution"


def test_automated_success_stops_at_human_playtest_not_promotion():
    states = automated_objective()
    states.update({"critic_quorum": "qualified", "critic_resolution": "qualified"})
    action = next_generated_action(ledger(states))
    assert action.action == "collect_human_playtest"
    assert action.scope == "human_fun"
    assert action.spend_class == "human"
    assert not action.terminal


def test_human_rejection_is_terminal_even_when_every_automated_gate_passed():
    states = automated_objective()
    states.update({
        "critic_quorum": "qualified",
        "critic_resolution": "qualified",
        "human_fun": "failed",
    })
    action = next_generated_action(ledger(states))
    assert action.action == "halt_player_rejection"
    assert action.terminal


def test_complete_player_evidence_is_the_only_promotion_terminal():
    states = automated_objective()
    states.update({
        "critic_quorum": "qualified",
        "critic_resolution": "qualified",
        "human_fun": "qualified",
    })
    action = next_generated_action(ledger(states))
    assert action.action == "promotion_eligible"
    assert action.terminal
    assert action.spend_class == "none"
