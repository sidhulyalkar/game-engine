import json

import pytest

from game_engine.evidence_artifacts import compile_staged_ledgers, compile_template_ledger


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


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
    # The dead build was stopped at M4, so compatibility promotion never ran.
    assert rows["dead"]["scope_states"]["cross_browser"] == "not_evaluated"

    assert rows["gap"]["scope_states"]["causal_controls"] == "incomplete"
    assert rows["gap"]["scope_states"]["cross_browser"] == "not_evaluated"

    index = json.loads((tmp_path / "ledgers" / "index.json").read_text())
    assert index["subjects"] == ["blocked", "dead", "gap", "good"]
    assert all((tmp_path / "ledgers" / name).exists() for name in index["ledgers"].values())


def test_staged_compiler_fails_closed_when_payload_has_no_subjects(tmp_path):
    staged = tmp_path / "staged-evidence.json"
    write_json(staged, {"status": "infrastructure_error"})
    with pytest.raises(ValueError, match="no build identities"):
        compile_staged_ledgers(staged, tmp_path / "ledgers")


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
    write_json(staged, {
        "semantic_qualified_build_ids": ["g"],
        "reference_browser_build_ids": ["g"],
        "behaviorally_qualified_build_ids": ["g"],
        "promotion_attempted": False,
        "cross_browser_build_ids": ["g"],
    })
    payload = compile_staged_ledgers(staged, tmp_path / "ledgers")["g"]
    assert payload["claims"]
    assert all(claim["artifact"] == str(staged) for claim in payload["claims"])
