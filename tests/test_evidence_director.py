import json

import pytest

from game_engine.evidence_director import EvidenceDirectedDirector


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def make_configs(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name in ("primary", "rescue", "build", "audit", "repair"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"name": name}) + "\n")
        rows[name] = path
    return rows


def make_brief(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "brief.json"
    path.write_text(json.dumps({"title": "fixture"}) + "\n")
    return path


def staged_pass(path, build_id="good"):
    write_json(path, {
        "semantic_qualified_build_ids": [build_id],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": [build_id],
        "behaviorally_qualified_build_ids": [build_id],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": [build_id],
    })


def make_director(tmp_path, *, seed=13, git_sha="abc123"):
    return EvidenceDirectedDirector.initialize(
        tmp_path / "evidence",
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=seed,
        browsers=("chromium", "firefox", "webkit"),
        git_sha=git_sha,
    )


def test_identity_is_idempotent_but_conflicting_experiment_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    configs = make_configs(tmp_path)
    brief = make_brief(tmp_path)

    first = EvidenceDirectedDirector.initialize(
        root,
        brief_path=brief,
        provider_configs=configs,
        seed=13,
        browsers=("chromium", "firefox", "webkit"),
        git_sha="abc123",
    )
    second = EvidenceDirectedDirector.initialize(
        root,
        brief_path=brief,
        provider_configs=configs,
        seed=13,
        browsers=("chromium", "firefox", "webkit"),
        git_sha="abc123",
    )
    assert first.identity == second.identity
    assert json.loads((root / "experiment-identity.json").read_text()) == first.identity

    with pytest.raises(ValueError, match="different experiment"):
        EvidenceDirectedDirector.initialize(
            root,
            brief_path=brief,
            provider_configs=configs,
            seed=14,
            browsers=("chromium", "firefox", "webkit"),
            git_sha="abc123",
        )


def test_run64_style_semantic_blocker_is_vetoed_and_shadow_scheduler_requests_source_repair(tmp_path):
    director = make_director(tmp_path, seed=64, git_sha="run64")
    staged = tmp_path / "staged.json"
    write_json(staged, {
        "semantic_qualified_build_ids": [],
        "semantic_blocked_build_ids": ["broken"],
        "reference_browser_build_ids": [],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": False,
        "cross_browser_build_ids": [],
    })

    summary = director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    row = summary["observations"]["broken"]
    assert row["promotion"]["status"] == "blocked_failure"
    assert row["promotion"]["failed_scopes"] == ["source_semantics"]
    assert row["scheduler"]["action"] == "repair_source_contract"
    assert row["scheduler"]["spend_class"] == "bounded_llm"
    assert row["scope_states"]["reference_browser"] == "not_evaluated"


def test_cross_browser_survivor_is_critic_eligible_and_shadow_scheduler_stops_before_human_claims(tmp_path):
    director = make_director(tmp_path, seed=17, git_sha="survivor")
    staged = tmp_path / "staged.json"
    staged_pass(staged)

    row = director.observe_staged_evidence(
        race="b",
        staged_evidence_path=staged,
    )["observations"]["good"]
    assert row["promotion"]["status"] == "eligible"
    assert row["scheduler"]["action"] == "run_independent_critics"
    assert row["scheduler"]["spend_class"] == "llm_critics"
    assert row["scope_states"]["critic_quorum"] == "not_evaluated"
    assert row["scope_states"]["critic_resolution"] == "not_evaluated"
    assert row["scope_states"]["human_fun"] == "not_evaluated"


def test_critic_repair_verdict_creates_new_derived_event_without_mutating_objective_ledger(tmp_path):
    director = make_director(tmp_path, seed=22, git_sha="critic-repair")
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    objective_path = tmp_path / "evidence" / "ledgers" / "generated-web" / "a" / "good.json"
    objective_before = objective_path.read_text()

    audit = tmp_path / "audit-summary.json"
    write_json(audit, {
        "ranking": [{"build_id": "good", "status": "repair", "critic_count": 2}],
    })
    summary = director.observe_critic_audit(
        race="a",
        lineage="generated-web",
        audit_summary_path=audit,
    )
    row = summary["observations"]["good"]
    assert row["stage"] == "critic_audit"
    assert row["scope_states"]["critic_quorum"] == "qualified"
    assert row["scope_states"]["critic_resolution"] == "repair_required"
    assert row["promotion"]["status"] == "blocked_repair_required"
    assert row["promotion"]["repair_scopes"] == ["critic_resolution"]
    assert row["scheduler"]["action"] == "repair_critic_findings"
    assert objective_path.read_text() == objective_before
    assert (
        tmp_path / "evidence" / "critic-ledgers" / "generated-web" / "a" / "good.json"
    ).exists()


def test_critic_advance_and_reject_are_distinct_shadow_outcomes(tmp_path):
    for verdict, action, promotion in (
        ("advance", "collect_human_playtest", "blocked_missing_evidence"),
        ("reject", "halt_critic_rejection", "blocked_failure"),
    ):
        case = tmp_path / verdict
        director = EvidenceDirectedDirector.initialize(
            case / "evidence",
            brief_path=make_brief(case),
            provider_configs=make_configs(case),
            seed=4,
            browsers=("chromium",),
            git_sha=verdict,
        )
        staged = case / "staged.json"
        staged_pass(staged)
        director.observe_staged_evidence(race="a", staged_evidence_path=staged)
        audit = case / "audit.json"
        write_json(audit, {
            "ranking": [{"build_id": "good", "status": verdict, "critic_count": 2}],
        })
        row = director.observe_critic_audit(
            race="a", lineage="generated-web", audit_summary_path=audit
        )["observations"]["good"]
        assert row["scheduler"]["action"] == action
        assert row["promotion"]["status"] == promotion
        if verdict == "advance":
            assert row["scope_states"]["human_fun"] == "not_evaluated"
        else:
            assert row["scheduler"]["terminal"] is True


def test_critic_audit_cannot_borrow_sibling_or_unobserved_lineage(tmp_path):
    director = make_director(tmp_path, seed=2, git_sha="critic-sibling")
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    audit = tmp_path / "audit.json"
    write_json(audit, {
        "ranking": [{"build_id": "other", "status": "advance", "critic_count": 2}],
    })
    with pytest.raises(ValueError, match="has no objective ledger"):
        director.observe_critic_audit(
            race="a", lineage="generated-web", audit_summary_path=audit
        )


def test_replaying_exact_observation_is_idempotent_and_does_not_duplicate_event(tmp_path):
    root = tmp_path / "evidence"
    director = EvidenceDirectedDirector.initialize(
        root,
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=9,
        browsers=("chromium",),
        git_sha="idempotent",
    )
    staged = tmp_path / "staged.json"
    staged_pass(staged)

    one = director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    two = director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    assert one == two
    rows = [json.loads(line) for line in (root / "shadow-events.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["build_id"] == "good"


def test_critic_observation_replay_is_idempotent_and_keeps_separate_event(tmp_path):
    director = make_director(tmp_path, seed=8, git_sha="critic-idempotent")
    staged = tmp_path / "staged.json"
    staged_pass(staged)
    director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    audit = tmp_path / "audit.json"
    write_json(audit, {
        "ranking": [{"build_id": "good", "status": "advance", "critic_count": 2}],
    })
    one = director.observe_critic_audit(
        race="a", lineage="generated-web", audit_summary_path=audit
    )
    two = director.observe_critic_audit(
        race="a", lineage="generated-web", audit_summary_path=audit
    )
    assert one == two
    events = [
        json.loads(line)
        for line in (tmp_path / "evidence" / "shadow-events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [row["stage"] for row in events] == ["staged_evidence", "critic_audit"]


def test_conflicting_replay_of_same_logical_observation_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    director = EvidenceDirectedDirector.initialize(
        root,
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=3,
        browsers=("chromium",),
        git_sha="conflict",
    )
    staged = tmp_path / "staged.json"
    write_json(staged, {
        "semantic_qualified_build_ids": ["x"],
        "reference_browser_build_ids": [],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": False,
        "cross_browser_build_ids": [],
    })
    director.observe_staged_evidence(race="a", staged_evidence_path=staged)

    write_json(staged, {
        "semantic_qualified_build_ids": ["x"],
        "reference_browser_build_ids": ["x"],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": False,
        "cross_browser_build_ids": [],
    })
    with pytest.raises(ValueError, match="conflicting immutable evidence event"):
        director.observe_staged_evidence(race="a", staged_evidence_path=staged)


def test_provider_performance_remains_shadow_only(tmp_path):
    root = tmp_path / "evidence"
    director = EvidenceDirectedDirector.initialize(
        root,
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=1,
        browsers=("chromium",),
        git_sha="provider-shadow",
    )
    payload = director.compile_provider_shadow(tmp_path / "run")
    assert payload["mode"] == "shadow"
    assert payload["routing_authority"] is False
    assert json.loads((root / "provider-performance.json").read_text())["routing_authority"] is False
