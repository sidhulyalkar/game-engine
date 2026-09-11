import json

from game_engine.evidence_shadow_cli import observe_tournament_run


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def make_inputs(tmp_path):
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"title": "fixture"}) + "\n")
    configs = {}
    for name in ("primary", "rescue", "build", "audit", "repair"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"name": name}) + "\n")
        configs[name] = path
    return brief, configs


def test_partial_failed_run_still_materializes_available_shadow_evidence(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    staged = run_root / "staged-a" / "staged-evidence.json"
    write_json(staged, {
        "semantic_qualified_build_ids": ["good"],
        "semantic_blocked_build_ids": ["bad"],
        "reference_browser_build_ids": ["good"],
        "behaviorally_qualified_build_ids": ["good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": ["good"],
    })

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=64,
        browsers=("chromium", "firefox", "webkit"),
        provider_configs=configs,
        git_sha="partial",
    )
    assert payload["routing_authority"] is False
    assert payload["errors"] == []
    assert len(payload["observed"]) == 1
    row = payload["observed"][0]
    assert row["lineage"] == "generated-web"
    assert row["scheduler_actions"] == {
        "bad": "repair_source_contract",
        "good": "run_independent_critics",
    }
    assert len(payload["skipped"]) == 5
    assert payload["provider_performance_written"] is True
    evidence = run_root / "evidence-directed"
    assert (evidence / "experiment-identity.json").exists()
    assert (evidence / "shadow-events.jsonl").exists()
    assert (evidence / "provider-performance.json").exists()
    assert (evidence / "shadow-run-summary.json").exists()


def test_behavioral_and_critic_repair_lineages_are_kept_distinct(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    common = {
        "semantic_qualified_build_ids": ["child"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["child"],
        "behaviorally_qualified_build_ids": ["child"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": ["child"],
    }
    write_json(run_root / "staged-repair-a" / "staged-evidence.json", common)
    write_json(
        run_root / "repair-cycle-b" / "staged-evidence" / "staged-evidence.json",
        common,
    )

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=7,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="lineages",
    )
    assert payload["errors"] == []
    assert {(row["race"], row["lineage"]) for row in payload["observed"]} == {
        ("a", "behavioral-repair"),
        ("b", "critic-repair"),
    }
    root = run_root / "evidence-directed" / "ledgers"
    assert (root / "behavioral-repair" / "a" / "child.json").exists()
    assert (root / "critic-repair" / "b" / "child.json").exists()


def test_missing_all_staged_artifacts_is_valid_shadow_observation_of_early_failure(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=1,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="early-failure",
    )
    assert payload["observed"] == []
    assert payload["errors"] == []
    assert len(payload["skipped"]) == 6
    assert payload["provider_performance_written"] is True
