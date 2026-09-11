import json
from dataclasses import dataclass

from game_engine.schema import Brief
from game_engine.swarm import ProviderCircuit, SwarmStudio


@dataclass
class _Spec:
    name: str = "provider"
    roles: tuple[str, ...] = ("wild_inventor", "byte_architect", "adversarial_designer")
    max_concurrency: int = 1


_VALID = {
    "title": "Prism Spring",
    "hook": "Stretch a rainbow spring and release through matching hazards.",
    "core_mechanic": "Movement stores spring energy; releasing converts tension into a directional strike whose hue determines valid targets.",
    "player_goal": "Chain accurate releases without being hit.",
    "controls": "Move with WASD and release with Space.",
    "core_loop": ["move", "stretch", "aim", "release"],
    "escalation": ["mixed hues", "moving hazards"],
    "visual_grammar": "rainbow tether, impact rings, readable silhouettes",
    "audio_grammar": "tension pitch rises before a bass impact",
    "category_fit": ["desktop"],
    "byte_hypothesis": "Canvas primitives, one spring solver, oscillator audio.",
    "risks": ["aim clarity"],
    "tags": ["spring", "precision"],
}


class _TransportFailClient:
    name = "provider"

    def __init__(self):
        self.calls = 0

    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("Provider transport failure for model test: TimeoutError")


class _RateLimitClient(_TransportFailClient):
    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("Provider HTTP 429 for model test")


class _MalformedClient(_TransportFailClient):
    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        return "not json"


class _ValidClient(_TransportFailClient):
    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        return json.dumps({"concepts": [_VALID]})


def test_two_consecutive_transport_failures_skip_queued_network_work():
    client = _TransportFailClient()
    _, _, contributions = SwarmStudio([(_Spec(), client)], max_workers=3).ideate(
        Brief(theme="Unicorns and Rainbows"), deterministic_seeds=4, concepts_per_call=1
    )

    assert client.calls == 2
    assert len(contributions) == 3
    assert sum(row.skipped for row in contributions) == 1
    assert sum(row.failure_class == "transport" for row in contributions) == 2
    assert sum(row.failure_class == "circuit_open" for row in contributions) == 1


def test_final_rate_limit_opens_circuit_immediately():
    client = _RateLimitClient()
    _, _, contributions = SwarmStudio([(_Spec(), client)], max_workers=3).ideate(
        Brief(theme="Unicorns and Rainbows"), deterministic_seeds=4, concepts_per_call=1
    )

    assert client.calls == 1
    assert sum(row.skipped for row in contributions) == 2
    assert sum(row.failure_class == "rate_limit" for row in contributions) == 1


def test_content_parse_failures_do_not_open_operational_circuit():
    client = _MalformedClient()
    _, _, contributions = SwarmStudio([(_Spec(), client)], max_workers=3).ideate(
        Brief(theme="Unicorns and Rainbows"), deterministic_seeds=4, concepts_per_call=1
    )

    assert client.calls == 3
    assert len(contributions) == 3
    assert not any(row.skipped for row in contributions)
    assert all(row.failure_class is None for row in contributions)
    assert all("JSONDecodeError" in (row.error or "") for row in contributions)


def test_success_resets_consecutive_operational_failure_streak():
    circuit = ProviderCircuit("provider")
    circuit.record_failure(RuntimeError("Provider transport failure: TimeoutError"))
    assert circuit.is_open is False
    circuit.record_success()
    circuit.record_failure(RuntimeError("Provider transport failure: TimeoutError"))
    assert circuit.is_open is False
    circuit.record_failure(RuntimeError("Provider HTTP 503 for model test"))
    assert circuit.is_open is True


def test_successful_calls_still_produce_concepts_with_circuit_present():
    client = _ValidClient()
    concepts, _, contributions = SwarmStudio([(_Spec(), client)], max_workers=3).ideate(
        Brief(theme="Unicorns and Rainbows"), deterministic_seeds=4, concepts_per_call=1
    )
    assert client.calls == 3
    assert all(row.ok for row in contributions)
    assert any(concept.title == "Prism Spring" for concept in concepts)
