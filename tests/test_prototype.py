from dataclasses import dataclass

from game_engine.prototype import PrototypeForge
from game_engine.schema import Brief, Concept


@dataclass
class FakeSpec:
    name: str = "builder-a"


class FakeBuilder:
    name = "builder-a"

    def complete(self, system: str, prompt: str) -> str:
        return '{"index_html":"<!doctype html><html><body><canvas id=c></canvas><p>WASD + SPACE</p><script>c.width=320;c.height=180</script></body></html>","design_notes":["tiny smoke prototype"]}'


def test_prototype_forge_writes_and_packages(tmp_path):
    concept = Concept(
        concept_id="abc", title="Tether", hook="hook", core_mechanic="spring",
        player_goal="score", controls="move and release", core_loop=["move", "release"],
        escalation=["faster"], visual_grammar="trails", audio_grammar="bleeps",
        category_fit=["desktop"], byte_hypothesis="canvas", risks=[], tags=[]
    )
    results = PrototypeForge([(FakeSpec(), FakeBuilder())], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), concept, tmp_path
    )
    assert results[0].ok
    assert results[0].compressed_bytes <= 2048
    assert (tmp_path / "builds.json").exists()
