from dataclasses import dataclass

from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio, _extract_json


@dataclass
class FakeSpec:
    name: str = "fake"
    roles: tuple[str, ...] = ("wild_inventor",)


class FakeClient:
    name = "fake"

    def complete(self, system: str, prompt: str) -> str:
        return '''{"concepts":[{"title":"Chromatic Tension","hook":"Stretch a rainbow tether to steer danger into targets.","core_mechanic":"Distance stores spring energy and hue selects which hazards can be struck.","player_goal":"Survive and chain precision rebounds.","controls":"Move plus one release action.","core_loop":["stretch","aim","release","reposition"],"escalation":["one hue","mixed hues","moving anchor boss"],"visual_grammar":"elastic rainbow trails and impact rings","audio_grammar":"procedural tension pitch and impact bass","category_fit":["desktop"],"byte_hypothesis":"Canvas lines, circles, shared spring math, WebAudio oscillators.","risks":["aim readability"],"tags":["spring","color-state","precision"]}]}'''


def test_json_extraction_from_fence():
    assert _extract_json('```json\n{"concepts": []}\n```') == {"concepts": []}


def test_swarm_accepts_provider_concepts():
    brief = Brief(theme="Unicorns and Rainbows")
    concepts, scores, contributions = SwarmStudio([(FakeSpec(), FakeClient())], max_workers=1).ideate(brief, deterministic_seeds=4, concepts_per_call=1)
    assert any("provider:fake" in c.tags for c in concepts)
    assert contributions[0].ok
    assert len(scores) == len(concepts)
