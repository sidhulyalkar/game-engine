import json
from dataclasses import dataclass

from game_engine.source_audit import (
    DIMENSIONS,
    CriticAudit,
    _complete_critic_audit,
    _parse_audit,
    aggregate_audits,
)


def valid_audit(verdict="reject", score=3):
    return json.dumps({
        "scores": {name: score for name in DIMENSIONS},
        "verdict": verdict,
        "summary": "Concrete source-level audit.",
        "findings": [{
            "severity": "blocker",
            "category": "logic",
            "evidence": "launch speed ignores stretch magnitude",
            "player_impact": "drag length cannot change the launch",
            "smallest_fix": "scale launch velocity by stretch length",
        }],
    })


@dataclass
class Completion:
    content: str
    finish_reason: str = "stop"
    usage: dict | None = None


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def complete_with_metadata(self, system, prompt):
        self.calls += 1
        self.prompts.append((system, prompt))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return Completion(value, usage={"completion_tokens": 17})


def test_malformed_nonempty_critic_gets_exactly_one_same_critic_schema_recovery(tmp_path):
    client = SequenceClient([
        '{"scores":{"concept_fidelity":3},"verdict":"reject" "summary":"broken"}',
        valid_audit(),
    ])
    result = _complete_critic_audit(
        client, "nemotron-critic", "nvidia/nemotron", "build-a", "audit-system", "audit-user", tmp_path
    )
    assert result.ok is True
    assert result.recovery_attempted is True
    assert result.initial_parse_error
    assert result.model_id == "nvidia/nemotron"
    assert result.finish_reason == "stop"
    assert result.recovery_finish_reason == "stop"
    assert result.raw_response_path and result.recovery_raw_response_path
    assert client.calls == 2
    assert "JSON serialization repairer" in client.prompts[1][0]
    assert "Do not add, delete, soften, strengthen, or re-evaluate findings" in client.prompts[1][0]


def test_valid_critic_never_spends_recovery_call(tmp_path):
    client = SequenceClient([valid_audit("advance", 8)])
    result = _complete_critic_audit(
        client, "kimi-critic", "moonshotai/kimi-k3", "build-a", "system", "prompt", tmp_path
    )
    assert result.ok is True
    assert result.recovery_attempted is False
    assert client.calls == 1
    assert result.raw_response_path
    assert result.recovery_raw_response_path is None


def test_failed_schema_recovery_remains_failed_evidence(tmp_path):
    client = SequenceClient(['{"verdict":"advance"}', '{}'])
    result = _complete_critic_audit(
        client, "critic", "model", "build-a", "system", "prompt", tmp_path
    )
    assert result.ok is False
    assert result.recovery_attempted is True
    assert result.initial_parse_error
    assert result.recovery_error
    assert client.calls == 2


def test_transport_failure_does_not_trigger_serialization_recovery(tmp_path):
    client = SequenceClient([TimeoutError("provider timeout")])
    result = _complete_critic_audit(
        client, "critic", "model", "build-a", "system", "prompt", tmp_path
    )
    assert result.ok is False
    assert result.recovery_attempted is False
    assert "TimeoutError" in result.error
    assert client.calls == 1


def test_incomplete_but_parseable_object_is_not_counted_as_a_critic():
    try:
        _parse_audit('{"scores":{},"verdict":"advance","summary":"x","findings":[]}', "critic", "build")
    except ValueError as exc:
        assert "missing dimensions" in str(exc)
    else:
        raise AssertionError("incomplete audit unexpectedly qualified")


def test_recovered_vote_is_still_only_one_vote_for_quorum(tmp_path):
    client = SequenceClient(['{bad json', valid_audit("reject", 2)])
    recovered = _complete_critic_audit(
        client, "critic-a", "model-a", "build-a", "system", "prompt", tmp_path
    )
    failed = CriticAudit(provider="critic-b", model_id="model-b", build_id="build-a", ok=False, error="timeout")
    result = aggregate_audits({"build_id": "build-a", "provider": "builder"}, [recovered, failed])
    assert result.critic_count == 1
    assert result.failed_critic_count == 1
    assert result.status == "insufficient_evidence"
