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


def staged(build_id):
    return {
        "semantic_qualified_build_ids": [build_id],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": [build_id],
        "behaviorally_qualified_build_ids": [build_id],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "promotion_attempted": True,
        "cross_browser_build_ids": [build_id],
    }


def test_partial_failed_run_still_materializes_available_shadow_evidence(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    source = staged("good")
    source["semantic_blocked_build_ids"] = ["bad"]
    write_json(run_root / "staged-a" / "staged-evidence.json", source)

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
    assert payload["critic_observed"] == []
    row = payload["observed"][0]
    assert row["lineage"] == "generated-web"
    assert row["scheduler_actions"] == {
        "bad": "repair_source_contract",
        "good": "run_independent_critics",
    }
    # Five staged lineages plus four critic-audit locations are absent.
    assert len(payload["skipped"]) == 9
    assert payload["provider_performance_written"] is True
    evidence = run_root / "evidence-directed"
    assert (evidence / "experiment-identity.json").exists()
    assert (evidence / "shadow-events.jsonl").exists()
    assert (evidence / "provider-performance.json").exists()
    assert (evidence / "shadow-run-summary.json").exists()


def test_top_level_critic_audit_resolves_to_original_generated_lineage(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    write_json(run_root / "staged-a" / "staged-evidence.json", staged("original"))
    write_json(run_root / "audit-a" / "audit-summary.json", {
        "ranking": [{"build_id": "original", "status": "repair", "critic_count": 2}],
    })

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=10,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="audit-original",
    )
    assert payload["errors"] == []
    assert len(payload["critic_observed"]) == 1
    critic = payload["critic_observed"][0]
    assert critic["race"] == "a"
    assert critic["lineage"] == "generated-web"
    assert critic["scheduler_actions"] == {"original": "repair_critic_findings"}
    assert critic["promotion_status"] == {"original": "blocked_repair_required"}


def test_top_level_critic_audit_resolves_to_behavioral_repair_when_parent_did_not_reach_critics(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    write_json(
        run_root / "staged-repair-b" / "staged-evidence.json",
        staged("behavior-child"),
    )
    write_json(run_root / "audit-b" / "audit-summary.json", {
        "ranking": [{"build_id": "behavior-child", "status": "advance", "critic_count": 2}],
    })

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=11,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="audit-behavior",
    )
    assert payload["errors"] == []
    critic = payload["critic_observed"][0]
    assert critic["lineage"] == "behavioral-repair"
    assert critic["scheduler_actions"] == {"behavior-child": "collect_human_playtest"}


def test_critic_repair_audit_resolves_only_to_critic_repair_lineage(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    write_json(
        run_root / "repair-cycle-a" / "staged-evidence" / "staged-evidence.json",
        staged("critic-child"),
    )
    write_json(run_root / "repair-cycle-a" / "audit" / "audit-summary.json", {
        "ranking": [{"build_id": "critic-child", "status": "reject", "critic_count": 2}],
    })

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=12,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="audit-critic-repair",
    )
    assert payload["errors"] == []
    critic = payload["critic_observed"][0]
    assert critic["lineage"] == "critic-repair"
    assert critic["scheduler_actions"] == {"critic-child": "halt_critic_rejection"}


def test_ambiguous_audit_lineage_fails_closed_in_shadow_summary(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    # Artificially reuse the same content identity in two lineages. The compiler
    # must report ambiguity instead of guessing which parent the critics judged.
    write_json(run_root / "staged-a" / "staged-evidence.json", staged("same"))
    write_json(run_root / "staged-repair-a" / "staged-evidence.json", staged("same"))
    write_json(run_root / "audit-a" / "audit-summary.json", {
        "ranking": [{"build_id": "same", "status": "advance", "critic_count": 2}],
    })

    payload = observe_tournament_run(
        run_root,
        brief_path=brief,
        seed=13,
        browsers=("chromium",),
        provider_configs=configs,
        git_sha="ambiguous",
    )
    assert payload["critic_observed"] == []
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["kind"] == "critic_audit"
    assert "resolve uniquely" in payload["errors"][0]["error"]


def test_behavioral_and_critic_repair_lineages_are_kept_distinct(tmp_path):
    brief, configs = make_inputs(tmp_path)
    run_root = tmp_path / "run"
    write_json(run_root / "staged-repair-a" / "staged-evidence.json", staged("child"))
    write_json(
        run_root / "repair-cycle-b" / "staged-evidence" / "staged-evidence.json",
        staged("child"),
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


def test_missing_all_artifacts_is_valid_shadow_observation_of_early_failure(tmp_path):
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
    assert payload["critic_observed"] == []
    assert payload["errors"] == []
    assert len(payload["skipped"]) == 10
    assert payload["provider_performance_written"] is True
