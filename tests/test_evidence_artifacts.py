import json

import pytest

from game_engine.evidence_artifacts import (
    compile_scheduler_decision,
    compile_staged_ledgers,
    compile_template_ledger,
    enrich_generated_ledger_with_critic_audit,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def staged_pass(path, build_id="g"):
    write_json(path, {
        "semantic_qualified_build_ids": [build_id],
        "reference_browser_build_ids": [build_id],
        "behaviorally_qualified_build_ids": [build_id],
        "promotion_attempted": True,
        "cross_browser_build_ids": [build_id],
    })


def test_staged_compiler_preserves_distinct_build_capabilities(tmp_path):
    staged = tmp_path / "staged-evidence.json"
    write_json(staged, {
        "semantic_qualified_build_ids": ["good", "dead", "gap"],
        "semantic_blocked_build_ids": ["blocked"],
        "reference_browser_build_ids": ["good", "dead", "gap"],
        "behaviorally_qualified_build_ids": ["good"],
        "behavioral_repair_build_ids": ["dead"],
        "insufficient_evidence_build_ids": ["gap"],
        "promotion_attempted": True,
        "cross_browser_build_ids": ["good"],
    })

    rows = compile_staged_ledgers(staged, tmp_path / "ledgers")
    assert sorted(rows) == ["blocked", "dead", "gap", "good"]
    assert rows["good"]["scope_states"]["source_semantics"] == "qualified"
    assert rows["good"]["scope_states"]["causal_controls"] == "qualified"
    assert rows["good"]["scope_states"]["cross_browser"] == "qualified"
    assert rows["good"]["scope_states"]["human_fun"] == "not_evaluated"

    assert rows["blocked"]["scope_states"]["source_semantics"] == "failed"
    assert rows["blocked"]["scope_states"]["reference_browser"] == "not_evaluated"

    assert rows["dead"]["scope_states"]["causal_controls"] == "failed"
    assert rows["dead"]["scope_states"]["cross_browser"] == "not_evaluated"

    assert rows["gap"]["scope_states"]["causal_controls"] == "incomplete"
    assert rows["gap"]["scope_states"]["cross_browser"] == "not_evaluated"

    index = json.loads((tmp_path / "ledgers" / "index.json").read_text())
    assert index["subjects"] == ["blocked", "dead", "gap", "good"]
    assert index["scheduler_mode"] == "shadow"
    assert index["shadow_scheduler_decisions"]["blocked"]["action"] == "repair_source_contract"
    assert index["shadow_scheduler_decisions"]["dead"]["action"] == "repair_behavior"
    assert index["shadow_scheduler_decisions"]["gap"]["action"] == "rerun_behavior_evidence"
    assert index["shadow_scheduler_decisions"]["good"]["action"] == "run_independent_critics"
    assert all((tmp_path / "ledgers" / name).exists() for name in index["ledgers"].values())


def test_staged_compiler_fails_closed_when_payload_has_no_subjects(tmp_path):
    staged = tmp_path / "staged-evidence.json"
    write_json(staged, {"status": "infrastructure_error"})
    with pytest.raises(ValueError, match="no build identities"):
        compile_staged_ledgers(staged, tmp_path / "ledgers")


def test_scheduler_decision_can_be_recompiled_from_ledger_without_running_any_action(tmp_path):
    staged = tmp_path / "staged-evidence.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    output = tmp_path / "decision.json"
    decision = compile_scheduler_decision(tmp_path / "ledgers" / "g.json", output)
    assert decision["mode"] == "shadow"
    assert decision["decision"]["action"] == "run_independent_critics"
    assert decision["decision"]["spend_class"] == "llm_critics"
    assert json.loads(output.read_text()) == decision


def test_critic_repair_verdict_enriches_ledger_without_touching_objective_claims(tmp_path):
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    original = json.loads((tmp_path / "ledgers" / "g.json").read_text())
    audit = tmp_path / "audit-summary.json"
    write_json(audit, {
        "ranking": [
            {"build_id": "g", "status": "repair", "critic_count": 2, "overall": 5.4},
        ]
    })

    enriched = enrich_generated_ledger_with_critic_audit(
        tmp_path / "ledgers" / "g.json",
        audit,
        tmp_path / "enriched.json",
    )
    states = enriched["scope_states"]
    for scope in (
        "source_semantics", "reference_browser", "causal_controls",
        "restart_integrity", "independent_pixels", "cross_browser",
    ):
        assert states[scope] == original["scope_states"][scope] == "qualified"
    assert states["critic_quorum"] == "qualified"
    assert states["critic_resolution"] == "repair_required"
    assert enriched["shadow_scheduler_decision"]["action"] == "repair_critic_findings"
    assert enriched["shadow_scheduler_decision"]["spend_class"] == "bounded_llm"


def test_critic_advance_verdict_moves_scheduler_to_human_playtest(tmp_path):
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    audit = tmp_path / "audit-summary.json"
    write_json(audit, {
        "ranking": [{"build_id": "g", "status": "advance", "critic_count": 2}],
    })
    enriched = enrich_generated_ledger_with_critic_audit(
        tmp_path / "ledgers" / "g.json", audit, tmp_path / "advance.json"
    )
    assert enriched["scope_states"]["critic_quorum"] == "qualified"
    assert enriched["scope_states"]["critic_resolution"] == "qualified"
    assert enriched["shadow_scheduler_decision"]["action"] == "collect_human_playtest"


def test_single_critic_does_not_make_repair_or_advance_authoritative(tmp_path):
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    audit = tmp_path / "audit-summary.json"
    write_json(audit, {
        "ranking": [{"build_id": "g", "status": "repair", "critic_count": 1}],
    })
    enriched = enrich_generated_ledger_with_critic_audit(
        tmp_path / "ledgers" / "g.json", audit, tmp_path / "single.json"
    )
    assert enriched["scope_states"]["critic_quorum"] == "incomplete"
    assert enriched["scope_states"]["critic_resolution"] == "incomplete"
    assert enriched["shadow_scheduler_decision"]["action"] == "rerun_independent_critics"


def test_critic_reject_verdict_is_terminal_in_scheduler(tmp_path):
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    audit = tmp_path / "audit-summary.json"
    write_json(audit, {
        "ranking": [{"build_id": "g", "status": "reject", "critic_count": 2}],
    })
    enriched = enrich_generated_ledger_with_critic_audit(
        tmp_path / "ledgers" / "g.json", audit, tmp_path / "reject.json"
    )
    assert enriched["scope_states"]["critic_resolution"] == "failed"
    assert enriched["shadow_scheduler_decision"]["action"] == "halt_critic_rejection"
    assert enriched["shadow_scheduler_decision"]["terminal"] is True


def test_critic_enrichment_fails_closed_on_sibling_or_duplicate_audit_rows(tmp_path):
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    compile_staged_ledgers(staged, tmp_path / "ledgers")
    missing = tmp_path / "missing.json"
    write_json(missing, {"ranking": [{"build_id": "other", "status": "advance", "critic_count": 2}]})
    with pytest.raises(ValueError, match="no row for build g"):
        enrich_generated_ledger_with_critic_audit(
            tmp_path / "ledgers" / "g.json", missing, tmp_path / "out.json"
        )

    duplicate = tmp_path / "duplicate.json"
    write_json(duplicate, {"ranking": [
        {"build_id": "g", "status": "advance", "critic_count": 2},
        {"build_id": "g", "status": "repair", "critic_count": 2},
    ]})
    with pytest.raises(ValueError, match="duplicate rows"):
        enrich_generated_ledger_with_critic_audit(
            tmp_path / "ledgers" / "g.json", duplicate, tmp_path / "out.json"
        )


def test_generated_scheduler_rejects_template_lineage_ownership(tmp_path):
    report = tmp_path / "report.json"
    write_json(report, {
        "status": "passed_checks",
        "scenario": {"template": "puma-platformer"},
        "scenario_sha256": "scenario",
        "source": {"sha256": "source"},
    })
    ledger = tmp_path / "template-ledger.json"
    compile_template_ledger(report, ledger)
    with pytest.raises(ValueError, match="does not own lineage"):
        compile_scheduler_decision(ledger)


def test_template_compiler_keeps_simulation_replay_and_regression_scopes_separate(tmp_path):
    report = tmp_path / "report.json"
    replay = tmp_path / "replay.json"
    write_json(report, {
        "status": "passed_checks",
        "scope": "Instrumented deterministic scenario only; no claim of fun or rendering.",
        "scenario": {"template": "unicorn-stampede"},
        "scenario_sha256": "scenario1234567890",
        "source": {"sha256": "source1234567890"},
    })
    write_json(replay, {"replay_matches": True})

    payload = compile_template_ledger(
        report,
        tmp_path / "ledger.json",
        replay_report_path=replay,
        regressions_passed=True,
    )
    states = payload["scope_states"]
    assert states["instrumented_simulation"] == "qualified"
    assert states["exact_replay"] == "qualified"
    assert states["template_regressions"] == "qualified"
    assert states["reference_browser"] == "not_evaluated"
    assert states["cross_browser"] == "not_evaluated"
    assert states["human_fun"] == "not_evaluated"
    assert payload["subject_id"] == "unicorn-stampede:source1234567890:scenario12345678"


def test_template_replay_mismatch_is_explicit_failure(tmp_path):
    report = tmp_path / "report.json"
    replay = tmp_path / "replay.json"
    write_json(report, {
        "status": "passed_checks",
        "scenario": {"template": "puma-platformer"},
        "scenario_sha256": "scenario",
        "source": {"sha256": "source"},
    })
    write_json(replay, {"replay_matches": False})
    payload = compile_template_ledger(report, tmp_path / "ledger.json", replay_report_path=replay)
    assert payload["scope_states"]["instrumented_simulation"] == "qualified"
    assert payload["scope_states"]["exact_replay"] == "failed"
    assert payload["scope_states"]["template_regressions"] == "not_evaluated"


def test_artifact_references_are_preserved_for_auditability(tmp_path):
    staged = tmp_path / "staged-evidence.json"
    staged_pass(staged)
    payload = compile_staged_ledgers(staged, tmp_path / "ledgers")["g"]
    assert payload["claims"]
    assert all(claim["artifact"] == str(staged) for claim in payload["claims"])
