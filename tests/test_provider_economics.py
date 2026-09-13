import json

from game_engine.provider_observation import (
    observation_from_usage,
    provider_token_counts,
    usage_with_observation,
)
from game_engine.provider_performance import compile_provider_performance
from game_engine.providers.openai_compatible import CompletionResult


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def test_usage_observation_keeps_native_tokens_and_namespaces_transport():
    result = CompletionResult(
        content="ok",
        finish_reason="stop",
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        elapsed_ms=1234.5,
        attempt_count=2,
    )
    usage = usage_with_observation(result)
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 7
    assert usage["_game_engine"] == {
        "elapsed_ms": 1234.5,
        "attempt_count": 2,
        "retry_count": 1,
    }
    assert observation_from_usage(usage)["retry_count"] == 1
    assert provider_token_counts(usage) == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }


def test_provider_performance_compiles_phase_specific_observed_economics(tmp_path):
    run = tmp_path / "run"
    write_json(run / "builds-a" / "builds.json", [
        {
            "provider": "builder-a",
            "build_id": "game-a",
            "ok": True,
            "compressed_bytes": 3000,
            "contract_repair_attempted": True,
            "contract_repair_remaining_blockers": [],
        }
    ])
    write_json(run / "builds-a" / "meta" / "builder-a-game-a.json", {
        "provider": "builder-a",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
            "_game_engine": {"elapsed_ms": 1000, "attempt_count": 1, "retry_count": 0},
        },
        "contract_repair_usage": {
            "prompt_tokens": 80,
            "completion_tokens": 100,
            "total_tokens": 180,
            "_game_engine": {"elapsed_ms": 500, "attempt_count": 2, "retry_count": 1},
        },
    })
    write_json(run / "audit-a" / "audits.json", [
        {
            "build_id": "game-a",
            "provider": "builder-a",
            "critic_audits": [
                {
                    "provider": "critic-a",
                    "ok": True,
                    "model_id": "critic-model",
                    "usage": {
                        "input_tokens": 50,
                        "output_tokens": 25,
                        "_game_engine": {"elapsed_ms": 250, "attempt_count": 1, "retry_count": 0},
                    },
                }
            ],
        }
    ])

    payload = compile_provider_performance(run)
    assert payload["routing_authority"] is False
    assert payload["economics_authority"] is False
    builder = payload["providers"]["builder-a"]["observed_economics"]["builder"]
    assert builder["observed_calls"] == 2
    assert builder["timing_observations"] == 2
    assert builder["total_elapsed_ms"] == 1500.0
    assert builder["mean_elapsed_ms"] == 750.0
    assert builder["total_attempts"] == 3
    assert builder["total_retries"] == 1
    assert builder["token_observations"] == 2
    assert builder["prompt_tokens"] == 180
    assert builder["completion_tokens"] == 300
    assert builder["total_tokens"] == 480

    critic = payload["providers"]["critic-a"]["observed_economics"]["critic"]
    assert critic["observed_calls"] == 1
    assert critic["total_elapsed_ms"] == 250.0
    assert critic["prompt_tokens"] == 50
    assert critic["completion_tokens"] == 25
    assert critic["total_tokens"] == 75


def test_missing_economics_stays_explicitly_missing(tmp_path):
    run = tmp_path / "run"
    write_json(run / "swarm-primary" / "contributions.json", [
        {
            "provider": "legacy-provider",
            "role": "inventor",
            "ok": True,
            "concept_ids": ["x"],
        }
    ])
    payload = compile_provider_performance(run)
    econ = payload["providers"]["legacy-provider"]["observed_economics"]["ideation"]
    assert econ["observed_calls"] == 0
    assert econ["timing_observations"] == 0
    assert econ["mean_elapsed_ms"] is None
    assert econ["token_observations"] == 0
    assert econ["total_tokens"] == 0
