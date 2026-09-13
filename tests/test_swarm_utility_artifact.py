import json
from dataclasses import dataclass

from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio


@dataclass
class _Spec:
    name: str = "fixture-provider"
    roles: tuple[str, ...] = ("wild_inventor",)
    max_concurrency: int = 1


_VALID = {
    "title": "Elastic Prism",
    "hook": "Stretch, aim, and release a rainbow spring.",
    "core_mechanic": "Movement stores tension and Space releases it into a directional strike.",
    "player_goal": "Survive while chaining accurate releases.",
    "controls": "WASD to move, Space to release.",
    "core_loop": ["move", "stretch", "release"],
    "escalation": ["faster hazards"],
    "visual_grammar": "bright tether and impact rings",
    "audio_grammar": "rising oscillator then impact",
    "category_fit": ["desktop"],
    "byte_hypothesis": "Canvas primitives and oscillator audio.",
    "risks": [],
    "tags": ["spring"],
}


class _ValidClient:
    name = "fixture-provider"

    def complete(self, system: str, prompt: str) -> str:
        return json.dumps({"concepts": [_VALID]})


class _FailClient:
    name = "fixture-provider"

    def complete(self, system: str, prompt: str) -> str:
        raise RuntimeError("Provider transport failure: TimeoutError")


def test_swarm_run_persists_assignment_latency_and_provider_utility(tmp_path):
    out = tmp_path / "swarm"
    payload = SwarmStudio([(_Spec(), _ValidClient())], max_workers=1).run(
        Brief(theme="Unicorns and Rainbows"),
        out,
        deterministic_seeds=4,
        concepts_per_call=1,
    )

    contributions = json.loads((out / "contributions.json").read_text())
    assert len(contributions) == 1
    assert contributions[0]["ok"] is True
    assert contributions[0]["elapsed_seconds"] is not None
    assert contributions[0]["elapsed_seconds"] >= 0

    utility = json.loads((out / "provider-utility.json").read_text())
    assert utility["routing_effect"] == "none"
    assert utility["providers"]["fixture-provider"]["successful_assignments"] == 1
    assert utility["providers"]["fixture-provider"]["latency_observations"] == 1
    assert payload["provider_utility_path"] == "provider-utility.json"
    assert payload["observed_call_seconds"] >= 0


def test_failed_transport_call_preserves_latency_for_future_routing(tmp_path):
    out = tmp_path / "swarm"
    SwarmStudio([(_Spec(), _FailClient())], max_workers=1).run(
        Brief(theme="Unicorns and Rainbows"),
        out,
        deterministic_seeds=4,
        concepts_per_call=1,
    )

    contribution = json.loads((out / "contributions.json").read_text())[0]
    assert contribution["ok"] is False
    assert contribution["failure_class"] == "transport"
    assert contribution["elapsed_seconds"] is not None
    assert contribution["elapsed_seconds"] >= 0

    utility = json.loads((out / "provider-utility.json").read_text())
    provider = utility["providers"]["fixture-provider"]
    assert provider["operational_failures"] == 1
    assert provider["latency_observations"] == 1
