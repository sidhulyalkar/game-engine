import json

from game_engine.provider_performance import compile_provider_performance


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def test_provider_performance_stays_phase_specific_and_descriptive(tmp_path):
    run = tmp_path / "run"
    write_json(run / "swarm-primary" / "contributions.json", [
        {"provider": "kimi", "model": "kimi-model", "role": "gameplay_director", "ok": False, "concept_ids": [], "failure_class": "transport", "skipped": False, "elapsed_seconds": 40.0},
        {"provider": "nemotron", "model": "nemotron-model", "role": "gameplay_director", "ok": True, "concept_ids": ["c1", "c2"], "skipped": False, "elapsed_seconds": 10.0},
    ])
    write_json(run / "swarm-rescue" / "contributions.json", [
        {"provider": "kimi", "model": "kimi-model", "role": "desktop_specialist", "ok": True, "concept_ids": ["c3"], "skipped": False, "elapsed_seconds": 12.0},
        {"provider": "nemotron", "model": "nemotron-model", "role": "competition_judge", "ok": False, "concept_ids": [], "failure_class": "circuit_open", "skipped": True, "elapsed_seconds": 0.001},
    ])

    write_json(run / "builds-a" / "builds.json", [
        {"provider": "nemotron", "build_id": "n-good", "ok": True, "compressed_bytes": 3000, "contract_repair_attempted": True, "contract_repair_remaining_blockers": []},
        {"provider": "kimi", "build_id": "k-bad", "ok": False, "compressed_bytes": None, "contract_repair_attempted": False},
    ])
    write_json(run / "builds-b" / "builds.json", [
        {"provider": "nemotron", "build_id": "n-dead", "ok": True, "compressed_bytes": 4000, "contract_repair_attempted": False},
    ])

    write_json(run / "staged-a" / "staged-evidence.json", {
        "semantic_qualified_build_ids": ["n-good"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["n-good"],
        "behaviorally_qualified_build_ids": ["n-good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "cross_browser_build_ids": ["n-good"],
    })
    write_json(run / "staged-b" / "staged-evidence.json", {
        "semantic_qualified_build_ids": ["n-dead"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["n-dead"],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": ["n-dead"],
        "insufficient_evidence_build_ids": [],
        "cross_browser_build_ids": [],
    })

    write_json(run / "audit-a" / "audits.json", [{
        "provider": "nemotron-builder",
        "build_id": "n-good",
        "critic_count": 1,
        "critic_audits": [
            {"provider": "kimi", "model_id": "kimi-model", "build_id": "n-good", "ok": False, "recovery_attempted": True},
            {"provider": "nemotron-critic", "model_id": "nemotron-model", "build_id": "n-good", "ok": True, "recovery_attempted": True},
        ],
    }])
    write_json(run / "behavior-repairs-b" / "builds.json", [
        {"provider": "kimi", "parent_build_id": "n-dead", "build_id": "k-fixed", "ok": True},
    ])
    write_json(run / "staged-repair-b" / "staged-evidence.json", {
        "semantic_qualified_build_ids": ["k-fixed"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["k-fixed"],
        "behaviorally_qualified_build_ids": ["k-fixed"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "cross_browser_build_ids": ["k-fixed"],
    })

    payload = compile_provider_performance(run, tmp_path / "provider-performance.json")
    assert payload["routing_authority"] is False
    providers = payload["providers"]

    nemotron = providers["nemotron"]
    assert nemotron["ideation"]["assignments"] == 2
    assert nemotron["ideation"]["successes"] == 1
    assert nemotron["ideation"]["skipped"] == 1
    assert nemotron["ideation"]["concepts_generated"] == 2
    assert nemotron["ideation"]["models"] == {"nemotron-model": 2}
    assert nemotron["ideation"]["latency_observations"] == 1
    assert nemotron["ideation"]["observed_call_seconds"] == 10.0
    assert nemotron["builder"]["attempts"] == 2
    assert nemotron["builder"]["successes"] == 2
    assert nemotron["builder"]["contract_repairs"] == 1
    assert nemotron["builder"]["contract_repair_survivors"] == 1
    assert nemotron["builder"]["mean_compressed_bytes"] == 3500.0
    assert nemotron["downstream"]["cross_browser_qualified"] == 1
    assert nemotron["downstream"]["behavioral_repair_required"] == 1

    kimi = providers["kimi"]
    assert kimi["ideation"]["successes"] == 1
    assert kimi["ideation"]["failures"] == 1
    assert kimi["ideation"]["failure_classes"] == {"transport": 1}
    assert kimi["ideation"]["latency_observations"] == 2
    assert kimi["ideation"]["observed_call_seconds"] == 52.0
    assert kimi["builder"]["attempts"] == 1
    assert kimi["builder"]["failures"] == 1
    assert kimi["critics"]["calls"] == 1
    assert kimi["critics"]["failures"] == 1
    assert kimi["critics"]["serialization_recoveries"] == 1
    assert kimi["critics"]["model_ids"] == {"kimi-model": 1}
    assert kimi["repairs"]["behavioral_attempts"] == 1
    assert kimi["repairs"]["behavioral_successes"] == 1
    assert kimi["downstream"]["cross_browser_qualified"] == 1

    assert providers["nemotron-critic"]["critics"]["calls"] == 1
    assert providers["nemotron-critic"]["critics"]["successes"] == 1
    assert providers["nemotron-critic"]["critics"]["successful_recoveries"] == 1
    assert "nemotron-builder" not in providers


def test_flat_legacy_critic_rows_remain_supported(tmp_path):
    run = tmp_path / "run"
    write_json(run / "audit-a" / "audits.json", [
        {"provider": "legacy-critic", "build_id": "x", "ok": True, "recovery_attempted": False},
    ])
    payload = compile_provider_performance(run)
    assert payload["providers"]["legacy-critic"]["critics"]["calls"] == 1
    assert payload["providers"]["legacy-critic"]["critics"]["successes"] == 1


def test_missing_latency_stays_unknown_not_zero(tmp_path):
    run = tmp_path / "run"
    write_json(run / "swarm-primary" / "contributions.json", [
        {"provider": "p", "role": "judge", "ok": True, "concept_ids": ["x"], "skipped": False},
    ])
    payload = compile_provider_performance(run)
    ideation = payload["providers"]["p"]["ideation"]
    assert ideation["latency_observations"] == 0
    assert ideation["observed_call_seconds"] == 0
    assert ideation["mean_call_seconds"] is None
    assert ideation["max_call_seconds"] is None


def test_missing_artifacts_produce_empty_shadow_ledger_not_fake_failures(tmp_path):
    payload = compile_provider_performance(tmp_path / "empty")
    assert payload["providers"] == {}
    assert payload["routing_authority"] is False
