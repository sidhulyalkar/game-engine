import json

import pytest

from game_engine.evidence_director import EvidenceDirectedDirector


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def make_configs(tmp_path):
    rows = {}
    for name in ("primary", "rescue", "build", "audit", "repair"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"name": name}) + "\n")
        rows[name] = path
    return rows


def make_brief(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps({"title": "fixture"}) + "\n")
    return path


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
    director = EvidenceDirectedDirector.initialize(
        tmp_path / "evidence",
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=64,
        browsers=("chromium", "firefox", "webkit"),
        git_sha="run64",
    )
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
    director = EvidenceDirectedDirector.initialize(
        tmp_path / "evidence",
        brief_path=make_brief(tmp_path),
        provider_configs=make_configs(tmp_path),
        seed=17,
        browsers=("chromium", "firefox", "webkit"),
        git_sha="survivor",
    )
    staged = tmp_path / "staged.json"
    write_json(staged, {
        "semantic_qualified_build_ids": ["good"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["good"],
        "behaviorally_qualified_build_ids": ["good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": ["good"],
    })

    row = director.observe_staged_evidence(
        race="b",
        staged_evidence_path=staged,
    )["observations"]["good"]
    assert row["promotion"]["status"] == "eligible"
    assert row["scheduler"]["action"] == "run_independent_critics"
    assert row["scheduler"]["spend_class"] == "llm_critics"
    assert row["scope_states"]["critic_quorum"] == "not_evaluated"
    assert row["scope_states"]["human_fun"] == "not_evaluated"


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
    write_json(staged, {
        "semantic_qualified_build_ids": ["good"],
        "reference_browser_build_ids": ["good"],
        "behaviorally_qualified_build_ids": ["good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": False,
        "cross_browser_build_ids": ["good"],
    })

    one = director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    two = director.observe_staged_evidence(race="a", staged_evidence_path=staged)
    assert one == two
    rows = [json.loads(line) for line in (root / "shadow-events.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["build_id"] == "good"


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
