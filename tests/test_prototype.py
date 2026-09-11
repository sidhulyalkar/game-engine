from dataclasses import dataclass
import zipfile

from game_engine.prototype import PrototypeForge, _extract_html_response
from game_engine.schema import Brief, Concept


@dataclass
class FakeSpec:
    name: str = "builder-a"


def _instrumented_html(extra_script: str = "") -> str:
    return (
        '<!doctype html><html><body><canvas id=c></canvas><p>WASD + SPACE</p><script>'
        'c.width=320;c.height=180;'
        "window.__GAME_ENGINE_TELEMETRY__={schema_version:'0.1',"
        "snapshot:()=>({elapsed_ms:0,tick:0,state:'playing',alive:true,game_over:false,score:0,progress:0,"
        "restart_count:0,entity_count:1,action_count:0,last_action_ms:null,core_mechanic_activations:0,"
        "progression_transitions:0,state_hash:'fresh'}),events:()=>[]};"
        + extra_script
        + '</script></body></html>'
    )


def _missing_telemetry_html() -> str:
    return '<!doctype html><html><body><canvas id=c></canvas><script>let score=0</script></body></html>'


class FakeBuilder:
    name = "builder-a"

    def complete(self, system: str, prompt: str) -> str:
        assert "Output HTML only" in prompt
        assert "window.__GAME_ENGINE_TELEMETRY__" in prompt
        assert "DO NOT call Math.random()" in prompt
        assert "before expensive evaluation" in prompt
        return _instrumented_html()


class BrokenContractBuilder:
    name = "broken-builder"

    def complete(self, system: str, prompt: str) -> str:
        return '<!doctype html><html><body><canvas id=c></canvas><script>let x=Math.random()</script></body></html>'


class SequenceBuilder:
    name = "builder-a"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected extra builder call")
        return self.responses.pop(0)


def _concept():
    return Concept(
        concept_id="abc", title="Tether", hook="hook", core_mechanic="spring",
        player_goal="score", controls="move and release", core_loop=["move", "release"],
        escalation=["faster"], visual_grammar="trails", audio_grammar="bleeps",
        category_fit=["desktop"], byte_hypothesis="canvas", risks=[], tags=[]
    )


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
    assert row.source_falsification_path
    assert row.source_falsification_blockers == 0
    assert row.recovery_attempted is False
    assert row.contract_repair_attempted is False
    assert (tmp_path / "builds.json").exists()
    assert (tmp_path / "game-spec.json").exists()

    with zipfile.ZipFile(row.zip_path) as zf:
        assert zf.namelist() == ["index.html"]


def test_deterministic_contract_blocker_gets_one_surgical_repair_before_packaging(tmp_path):
    client = SequenceBuilder([_missing_telemetry_html(), _instrumented_html()])
    row = PrototypeForge([(FakeSpec(), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok is True
    assert client.calls == 2
    assert row.contract_repair_attempted is True
    assert row.contract_repair_parent_build_id
    assert row.contract_repair_parent_build_id != row.build_id
    assert row.contract_repair_raw_response_path and "contract-repair" in row.contract_repair_raw_response_path
    assert row.contract_repair_remaining_blockers == []
    assert row.source_falsification_blockers == 0
    assert row.zip_path is not None
    assert row.response_format == "contract-repaired-raw-html"
    assert "OBJECTIVE BLOCKERS TO FIX" in client.prompts[1]
    assert "missing_telemetry_contract" in client.prompts[1]
    assert any("deterministic contract repair" in warning for warning in row.warnings)


def test_source_contract_blocker_fails_closed_after_exactly_one_repair(tmp_path):
    client = SequenceBuilder([_missing_telemetry_html(), _missing_telemetry_html()])
    row = PrototypeForge([(FakeSpec("broken"), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok is False
    assert client.calls == 2
    assert row.build_id != "failed"
    assert row.source_dir is not None
    assert row.raw_response_path is not None
    assert row.contract_repair_attempted is True
    assert row.contract_repair_raw_response_path
    assert row.contract_repair_remaining_blockers == ["missing_telemetry_contract"]
    assert row.source_falsification_path is not None
    assert row.source_falsification_blockers == 1
    assert row.zip_path is None
    assert row.compressed_bytes is None
    assert "SourceFalsificationError after bounded contract repair" in row.error
    assert not (tmp_path / "dist").exists()


def test_multiple_source_blockers_receive_one_repair_not_retry_spam(tmp_path):
    bad = '<!doctype html><html><body><canvas id=c></canvas><script>let x=Math.random()</script></body></html>'
    client = SequenceBuilder([bad, bad])
    row = PrototypeForge([(FakeSpec("broken"), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok is False
    assert client.calls == 2
    assert row.contract_repair_attempted is True
    assert set(row.contract_repair_remaining_blockers) == {"nondeterministic_rng", "missing_telemetry_contract"}
    assert "nondeterministic_rng" in client.prompts[1]
    assert "missing_telemetry_contract" in client.prompts[1]


def test_truncated_html_gets_one_full_document_recovery(tmp_path):
    truncated = "<!doctype html><html><body><canvas></canvas><script>let x="
    complete = _instrumented_html("let x=1")
    client = SequenceBuilder([truncated, complete])

    row = PrototypeForge([(FakeSpec(), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok
    assert client.calls == 2
    assert row.recovery_attempted is True
    assert row.contract_repair_attempted is False
    assert row.raw_response_path and "initial" in row.raw_response_path
    assert row.recovery_raw_response_path and "recovery" in row.recovery_raw_response_path
    assert row.response_format == "recovered-raw-html"
    assert row.source_falsification_blockers == 0
    assert any("truncation recovery" in warning for warning in row.warnings)


def test_non_html_failure_does_not_spend_recovery_or_contract_repair_call(tmp_path):
    client = SequenceBuilder(["I cannot build that game today."])
    row = PrototypeForge([(FakeSpec(), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok is False
    assert client.calls == 1
    assert row.recovery_attempted is False
    assert row.contract_repair_attempted is False
    assert "no HTML document" in row.error


def test_second_truncation_fails_closed_after_one_recovery(tmp_path):
    client = SequenceBuilder([
        "<!doctype html><html><body><script>let x=",
        "<!doctype html><html><body><script>let x=1;let y=",
    ])
    row = PrototypeForge([(FakeSpec(), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", size_limit_bytes=2048), _concept(), tmp_path
    )[0]

    assert row.ok is False
    assert client.calls == 2
    assert row.recovery_attempted is True
    assert row.contract_repair_attempted is False
    assert row.recovery_raw_response_path
    assert "no closing </html>" in row.error
