import json

from game_engine.provider_performance import compile_provider_performance


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def test_repair_provider_ledger_does_not_count_circuit_skip_as_paid_attempt(tmp_path):
    run = tmp_path / "run"
    write_json(run / "behavior-repairs-a" / "builds.json", [
        {
            "provider": "kimi-repairer",
            "parent_build_id": "a",
            "build_id": "failed",
            "ok": False,
            "skipped": False,
            "failure_class": "request_contract",
        }
    ])
    write_json(run / "behavior-repairs-b" / "builds.json", [
        {
            "provider": "kimi-repairer",
            "parent_build_id": "b",
            "build_id": "failed",
            "ok": False,
            "skipped": True,
            "failure_class": "circuit_open",
        }
    ])

    payload = compile_provider_performance(run)
    repairs = payload["providers"]["kimi-repairer"]["repairs"]
    assert repairs["behavioral_attempts"] == 1
    assert repairs["behavioral_successes"] == 0
    assert repairs["skipped"] == 1
    assert repairs["failure_classes"] == {
        "request_contract": 1,
        "circuit_open": 1,
    }
