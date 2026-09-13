import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from game_engine.behavior_repair import BehavioralRepairForge
from game_engine.config import ProviderSpec, load_provider_specs
from game_engine.provider_health import ProviderCircuit, classify_provider_failure
from game_engine.schema import Brief, Concept


@dataclass
class Spec:
    name: str


class RequestContractClient:
    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        raise RuntimeError(
            'Provider HTTP 400 for model moonshotai/kimi-k3: '
            '{"message":"Validation: `top_p` is immutable for this model and must be 0.95, got 0.9"}'
        )


class MalformedHtmlClient:
    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        return "I repaired it but forgot to return the HTML document."


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def make_behavior_root(tmp_path):
    root = tmp_path / "behavior"
    write_json(root / "evidence-broker.json", {
        "decisions": [{
            "build_id": "restart-stale",
            "status": "behavioral_repair",
            "blockers": ["fresh-run restart contract failed"],
            "evidence_gaps": [],
        }],
        "behavioral_repair_build_ids": ["restart-stale"],
    })
    write_json(root / "action-causality" / "action-summary.json", {"builds": []})
    write_json(root / "restart" / "restart-summary.json", {"cases": []})
    write_json(root / "agency" / "playtest-summary.json", {"builds": []})
    return root


def concept():
    return Concept(
        concept_id="fixture",
        title="Fixture",
        hook="fixture",
        core_mechanic="press to mutate and restart",
        player_goal="mutate then restart",
        controls="Space, R",
        core_loop=["press", "restart"],
        escalation=["repeat"],
        visual_grammar="canvas",
        audio_grammar="bleep",
        category_fit=["desktop"],
        byte_hypothesis="tiny",
        risks=[],
        tags=[],
    )


def test_kimi_request_contract_is_rejected_before_network_spend():
    with pytest.raises(ValueError, match="model-fixed top_p"):
        ProviderSpec.from_dict({
            "name": "bad-kimi-repairer",
            "model": "moonshotai/kimi-k3",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "api_key_env": "NVIDIA_API_KEY",
            "roles": [],
            "temperature": 1.0,
            "top_p": 0.9,
        })


def test_repository_repair_config_uses_valid_bounded_kimi_profile():
    specs = load_provider_specs(Path("studio.nvidia.repair.json"))
    kimi = next(spec for spec in specs if spec.model == "moonshotai/kimi-k3")
    assert kimi.temperature == 1.0
    assert kimi.top_p is None
    assert kimi.extra_body == {"reasoning_effort": "low"}


def test_request_contract_failure_opens_provider_circuit_immediately():
    exc = RuntimeError(
        'Provider HTTP 400 for model moonshotai/kimi-k3: '
        'Validation: `top_p` is immutable and must be 0.95'
    )
    assert classify_provider_failure(exc) == "request_contract"
    circuit = ProviderCircuit("kimi")
    assert circuit.record_failure(exc) == "request_contract"
    assert circuit.is_open is True
    assert circuit.reason == "request_contract"


def test_request_contract_is_paid_once_across_repair_forges(tmp_path):
    behavior_root = make_behavior_root(tmp_path)
    client = RequestContractClient()
    clients = [(Spec("kimi-repairer"), client)]
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    builds_root = Path("tests/game_corpus/restart-stale")

    first = BehavioralRepairForge(clients, max_workers=1).build(
        brief, concept(), builds_root, behavior_root, tmp_path / "repair-a"
    )
    assert client.calls == 1
    assert first[0].failure_class == "request_contract"
    assert first[0].skipped is False

    second = BehavioralRepairForge(clients, max_workers=1).build(
        brief, concept(), builds_root, behavior_root, tmp_path / "repair-b"
    )
    assert client.calls == 1, "race B must not repay a deterministic request-contract failure"
    assert second[0].failure_class == "circuit_open"
    assert second[0].skipped is True
    manifest = json.loads((tmp_path / "repair-b" / "behavior-repair-manifest.json").read_text())
    assert manifest["attempted_children"] == 0
    assert manifest["skipped_children"] == 1


def test_malformed_html_does_not_open_operational_circuit(tmp_path):
    behavior_root = make_behavior_root(tmp_path)
    client = MalformedHtmlClient()
    clients = [(Spec("content-bad-repairer"), client)]
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    builds_root = Path("tests/game_corpus/restart-stale")

    first = BehavioralRepairForge(clients, max_workers=1).build(
        brief, concept(), builds_root, behavior_root, tmp_path / "malformed-a"
    )
    second = BehavioralRepairForge(clients, max_workers=1).build(
        brief, concept(), builds_root, behavior_root, tmp_path / "malformed-b"
    )
    assert client.calls == 2
    assert first[0].failure_class == "content_or_schema"
    assert second[0].failure_class == "content_or_schema"
    assert not first[0].skipped and not second[0].skipped
