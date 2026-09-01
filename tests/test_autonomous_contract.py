import json
from dataclasses import dataclass

from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio


@dataclass
class FakeSpec:
    name: str = "fake"
    roles: tuple[str, ...] = ("wild_inventor",)


class FakeClient:
    name = "fake"

    def complete(self, system: str, prompt: str) -> str:
        return '''{"concepts":[{"title":"Prism Hoof","hook":"Kick a rainbow into shapes that become the arena.","core_mechanic":"Your movement bends a persistent rainbow rail and enemies collide with its geometry.","player_goal":"Survive while sculpting safer and higher-scoring routes.","controls":"Move and release to lock a curve.","core_loop":["move","bend","lock","route"],"escalation":["single pursuer","color gates","boss cuts the rail"],"visual_grammar":"bright spline trails, silhouettes, impact sparks","audio_grammar":"pitch follows curvature and impacts trigger tiny chord stabs","category_fit":["desktop"],"byte_hypothesis":"Canvas paths and a compact point ring buffer share rendering and collision data.","risks":["rail readability"],"tags":["rail","geometry"]}]}'''


def test_swarm_run_emits_buildable_winner_contract(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows")
    out = tmp_path / "swarm"
    manifest = SwarmStudio([(FakeSpec(), FakeClient())], seed=7, max_workers=1).run(
        brief, out, deterministic_seeds=4, concepts_per_call=1
    )
    winner = json.loads((out / "winner.json").read_text())
    assert winner["brief"]["theme"] == "Unicorns and Rainbows"
    assert winner["concept"]["concept_id"] == manifest["winner_id"]
    assert winner["scorecard"]["concept_id"] == manifest["winner_id"]
    assert winner["swarm"]["successful_providers"] == ["fake"]
