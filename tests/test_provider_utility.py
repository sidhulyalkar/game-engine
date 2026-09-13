import json

from game_engine.provider_utility import (
    build_provider_utility_ledger,
    write_provider_utility_ledger,
)


def test_provider_utility_excludes_circuit_skips_from_network_attempts(tmp_path):
    path = tmp_path / "contributions.json"
    path.write_text(json.dumps([
        {
            "provider": "nemotron",
            "role": "gameplay_director",
            "ok": True,
            "concept_ids": ["a", "b"],
            "warnings": [],
            "failure_class": None,
            "skipped": False,
            "elapsed_seconds": 12.0,
        },
        {
            "provider": "nemotron",
            "role": "gameplay_director",
            "ok": False,
            "concept_ids": [],
            "warnings": [],
            "failure_class": "transport",
            "skipped": False,
            "elapsed_seconds": 30.0,
        },
        {
            "provider": "nemotron",
            "role": "gameplay_director",
            "ok": False,
            "concept_ids": [],
            "warnings": [],
            "failure_class": "circuit_open",
            "skipped": True,
            "elapsed_seconds": 0.001,
        },
    ]))

    ledger = build_provider_utility_ledger([path])
    row = ledger["providers"]["nemotron"]
    assert row["scheduled_assignments"] == 3
    assert row["attempted_assignments"] == 2
    assert row["successful_assignments"] == 1
    assert row["failed_assignments"] == 1
    assert row["skipped_assignments"] == 1
    assert row["operational_failures"] == 1
    assert row["success_rate"] == 0.5
    assert row["smoothed_reliability"] == 0.5
    assert row["accepted_concepts"] == 2
    assert row["concepts_per_attempt"] == 1.0
    assert row["observed_call_seconds"] == 42.0
    assert row["mean_call_seconds"] == 21.0
    assert row["max_call_seconds"] == 30.0
    assert row["latency_observations"] == 2


def test_provider_utility_separates_role_specific_behavior_and_schema_failures(tmp_path):
    path = tmp_path / "contributions.json"
    path.write_text(json.dumps([
        {
            "provider": "kimi",
            "role": "competition_judge",
            "ok": True,
            "concept_ids": ["x"],
            "warnings": ["concept[1] rejected: missing fields"],
            "skipped": False,
            "failure_class": None,
            "elapsed_seconds": 8.0,
        },
        {
            "provider": "kimi",
            "role": "desktop_specialist",
            "ok": False,
            "concept_ids": [],
            "warnings": [],
            "skipped": False,
            "failure_class": None,
            "error": "JSONDecodeError",
            "elapsed_seconds": 9.0,
        },
    ]))

    ledger = build_provider_utility_ledger([path])
    rows = {(row["provider"], row["role"]): row for row in ledger["provider_roles"]}
    judge = rows[("kimi", "competition_judge")]
    desktop = rows[("kimi", "desktop_specialist")]
    assert judge["successful_assignments"] == 1
    assert judge["partially_rejected_concepts"] == 1
    assert desktop["content_or_schema_failures"] == 1
    assert desktop["operational_failures"] == 0
    assert ledger["policy"] == "measurement-only"
    assert ledger["routing_effect"] == "none"


def test_provider_utility_aggregates_multiple_swarm_stages_and_persists(tmp_path):
    primary = tmp_path / "primary.json"
    rescue = tmp_path / "rescue.json"
    primary.write_text(json.dumps([
        {
            "provider": "nemotron",
            "role": "wild_inventor",
            "ok": True,
            "concept_ids": ["a"],
            "warnings": [],
            "skipped": False,
            "failure_class": None,
            "elapsed_seconds": 2.0,
        }
    ]))
    rescue.write_text(json.dumps([
        {
            "provider": "nemotron",
            "role": "desktop_specialist",
            "ok": True,
            "concept_ids": ["b", "c"],
            "warnings": [],
            "skipped": False,
            "failure_class": None,
            "elapsed_seconds": 3.0,
        }
    ]))

    output = tmp_path / "ledger.json"
    ledger = write_provider_utility_ledger([primary, rescue], output)
    persisted = json.loads(output.read_text())
    assert ledger == persisted
    assert persisted["observations"] == 2
    assert persisted["providers"]["nemotron"]["accepted_concepts"] == 3
    assert persisted["providers"]["nemotron"]["observed_call_seconds"] == 5.0
    assert persisted["sources"] == [str(primary), str(rescue)]
