import json
import threading
import time
from dataclasses import dataclass

from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio, _extract_json


@dataclass
class FakeSpec:
    name: str = "fake"
    roles: tuple[str, ...] = ("wild_inventor",)
    max_concurrency: int = 1


_VALID_CONCEPT = {
    "title": "Chromatic Tension",
    "hook": "Stretch a rainbow tether to steer danger into targets.",
    "core_mechanic": "Distance stores spring energy and hue selects which hazards can be struck.",
    "player_goal": "Survive and chain precision rebounds.",
    "controls": "Move plus one release action.",
    "core_loop": ["stretch", "aim", "release", "reposition"],
    "escalation": ["one hue", "mixed hues", "moving anchor boss"],
    "visual_grammar": "elastic rainbow trails and impact rings",
    "audio_grammar": "procedural tension pitch and impact bass",
    "category_fit": ["desktop"],
    "byte_hypothesis": "Canvas lines, circles, shared spring math, WebAudio oscillators.",
    "risks": ["aim readability"],
    "tags": ["spring", "color-state", "precision"],
}


class FakeClient:
    name = "fake"

    def complete(self, system: str, prompt: str) -> str:
        return json.dumps({"concepts": [_VALID_CONCEPT]})


def test_json_extraction_from_fence():
    assert _extract_json('```json\n{"concepts": []}\n```') == {"concepts": []}


def test_swarm_accepts_provider_concepts():
    brief = Brief(theme="Unicorns and Rainbows")
    concepts, scores, contributions = SwarmStudio([(FakeSpec(), FakeClient())], max_workers=1).ideate(brief, deterministic_seeds=4, concepts_per_call=1)
    assert any("provider:fake" in c.tags for c in concepts)
    assert contributions[0].ok
    assert len(scores) == len(concepts)


def test_provider_local_concurrency_is_bounded():
    @dataclass
    class TwoRoleSpec:
        name: str = "bounded"
        roles: tuple[str, ...] = ("wild_inventor", "byte_architect")
        max_concurrency: int = 1

    class TrackingClient(FakeClient):
        name = "bounded"

        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def complete(self, system: str, prompt: str) -> str:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.02)
                return super().complete(system, prompt)
            finally:
                with self.lock:
                    self.active -= 1

    client = TrackingClient()
    brief = Brief(theme="Unicorns and Rainbows")
    _, _, contributions = SwarmStudio([(TwoRoleSpec(), client)], max_workers=4).ideate(
        brief, deterministic_seeds=4, concepts_per_call=1
    )
    assert len(contributions) == 2
    assert all(row.ok for row in contributions)
    assert client.max_active == 1


def test_partial_model_output_keeps_valid_concepts_and_records_rejection():
    class PartialClient(FakeClient):
        def complete(self, system: str, prompt: str) -> str:
            over_scoped = dict(_VALID_CONCEPT)
            over_scoped["title"] = "Everything Everywhere Unicorn"
            over_scoped["core_mechanic"] = " ".join(["system"] * 121)
            return json.dumps({"concepts": [over_scoped, _VALID_CONCEPT]})

    brief = Brief(theme="Unicorns and Rainbows")
    concepts, _, contributions = SwarmStudio([(FakeSpec(), PartialClient())], max_workers=1).ideate(
        brief, deterministic_seeds=4, concepts_per_call=2
    )
    contribution = contributions[0]
    assert contribution.ok
    assert len(contribution.concept_ids) == 1
    assert contribution.warnings
    assert "core_mechanic exceeds 120 words" in contribution.warnings[0]
    assert any(c.title == "Chromatic Tension" and "provider:fake" in c.tags for c in concepts)
