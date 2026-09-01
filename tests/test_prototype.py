from dataclasses import dataclass
import zipfile

from game_engine.game_spec import compile_game_spec
from game_engine.prototype import PrototypeForge, _extract_html_response, builder_prompt
from game_engine.schema import Brief, Concept


@dataclass
class FakeSpec:
    name: str = "builder-a"


class FakeBuilder:
    name = "builder-a"

    def complete(self, system: str, prompt: str) -> str:
        assert "Output HTML only" in prompt
        assert "__GAME_ENGINE_TELEMETRY__" in prompt
        return '<!doctype html><html><body><canvas id=c></canvas><p>WASD + SPACE</p><script>c.width=320;c.height=180</script></body></html>'


def _concept():
    return Concept(
        concept_id="abc", title="Tether", hook="hook", core_mechanic="spring",
        player_goal="score", controls="move and release", core_loop=["move", "release"],
        escalation=["faster"], visual_grammar="trails", audio_grammar="bleeps",
        category_fit=["desktop"], byte_hypothesis="canvas", risks=[], tags=[]
    )


def test_builder_prompt_contains_literal_event_shape_and_telemetry_contract():
    brief = Brief(theme="Unicorns and Rainbows")
    spec = compile_game_spec(brief, _concept())
    _, prompt = builder_prompt(brief, spec)
    assert "each event is `{type, at_ms}`" in prompt
    assert "window.__GAME_ENGINE_TELEMETRY__" in prompt
    assert "core_mechanic_activations" in prompt


def test_extract_html_accepts_raw_fenced_and_legacy_json():
    raw = "<!doctype html><html><body>x</body></html>"
    assert _extract_html_response(raw) == (raw, "raw-html")
    assert _extract_html_response(f"```html\n{raw}\n```") == (raw, "fenced-html")
    legacy = '{"index_html":"<html><body>x</body></html>"}'
    assert _extract_html_response(legacy) == ("<html><body>x</body></html>", "legacy-json")


def test_extract_html_salvages_wrapper_prose():
    html = "<html><body>play</body></html>"
    recovered, response_format = _extract_html_response(f"Here it is:\n{html}\nDone")
    assert recovered == html
    assert response_format == "raw-html"


def test_prototype_forge_writes_and_packages_only_game_files(tmp_path):
    results = PrototypeForge([(FakeSpec(), FakeBuilder())], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )
    row = results[0]
    assert row.ok
    assert row.compressed_bytes <= 2048
    assert row.response_format == "raw-html"
    assert row.raw_response_path
    assert row.game_spec_path
    assert any("telemetry" in warning.lower() for warning in row.warnings)
    assert (tmp_path / "builds.json").exists()
    assert (tmp_path / "game-spec.json").exists()

    with zipfile.ZipFile(row.zip_path) as zf:
        assert zf.namelist() == ["index.html"]
