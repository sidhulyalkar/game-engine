import json
from pathlib import Path

from game_engine.source_falsification import SourceFalsificationLab, analyze_source


CORPUS = Path("tests/game_corpus/run64-tension-trail")


def _spec():
    return json.loads((CORPUS / "game-spec.json").read_text())


def test_exact_run64_cross_browser_survivor_is_now_rejected_before_browser_spend(tmp_path):
    result = SourceFalsificationLab().run(CORPUS, tmp_path / "evidence")
    assert result["full_pass_build_ids"] == []
    assert result["blocked_build_ids"] == ["b97d9a0640"]
    row = result["rows"][0]
    codes = {finding["code"] for finding in row["findings"]}
    assert {
        "stretch_power_normalized_away",
        "double_scaled_acceleration_dt",
        "keyboard_listener_on_unfocusable_canvas",
        "declared_state_cap_unused",
        "promised_audio_missing",
    }.issubset(codes)
    blocker_codes = {
        finding["code"] for finding in row["findings"] if finding["severity"] == "blocker"
    }
    assert {
        "stretch_power_normalized_away",
        "double_scaled_acceleration_dt",
        "keyboard_listener_on_unfocusable_canvas",
    }.issubset(blocker_codes)


def test_run64_all_browser_failure_telemetry_member_collision_is_static_blocker():
    source = r"""
    <canvas id="c"></canvas><script>
    const telemetry={
      schema_version:'0.1',
      events:[],
      _maxEvents:256,
      _addEvent(type){if(this.events.length>=this._maxEvents)this.events.shift();this.events.push({type});},
      snapshot(){return {score:0}},
      events(){return this.events.slice()}
    };
    window.__GAME_ENGINE_TELEMETRY__=telemetry;
    telemetry._addEvent('run_start');
    </script>
    """
    report = analyze_source(source, {"telemetry_contract": {"events": ["run_start"]}})
    assert report["qualified"] is False
    assert "duplicate_telemetry_events_member" in {row["code"] for row in report["findings"]}


def test_real_stretch_power_dependence_is_not_misclassified_as_constant_launch():
    source = r"""
    <script>
    const dx=20,dy=10,dist=Math.hypot(dx,dy);
    unicorn.vx=-(dx/dist)*dist*0.3;
    unicorn.vy=-(dy/dist)*dist*0.3;
    </script>
    """
    spec = {"interaction_invariant": "Drag farther for more launch power."}
    codes = {row["code"] for row in analyze_source(source, spec)["findings"]}
    assert "stretch_power_normalized_away" not in codes


def test_focusable_canvas_keyboard_binding_is_not_rejected():
    source = r"""
    <canvas id="c" tabindex="0"></canvas><script>
    const canvas=document.getElementById('c');
    canvas.addEventListener('keydown',e=>{if(e.key==='r')reset()});
    </script>
    """
    codes = {row["code"] for row in analyze_source(source, {})["findings"]}
    assert "keyboard_listener_on_unfocusable_canvas" not in codes


def test_single_dt_acceleration_and_enforced_cap_are_not_rejected():
    source = r"""
    <script>
    const STORM_MAX=32;
    let storm=0;
    function update(dt){unicorn.ay=18;unicorn.vy+=unicorn.ay*dt}
    function charge(len){storm=Math.min(STORM_MAX,storm+len/10)}
    </script>
    """
    spec = {"timing_contract": {"delta_time_seconds": True}}
    codes = {row["code"] for row in analyze_source(source, spec)["findings"]}
    assert "double_scaled_acceleration_dt" not in codes
    assert "declared_state_cap_unused" not in codes


def test_missing_promised_audio_is_quality_major_not_playability_blocker():
    report = analyze_source("<script>let score=0</script>", {
        "sensory_contract": {"audio": "WebAudio spring pluck tied to stretch power."}
    })
    findings = {row["code"]: row for row in report["findings"]}
    assert findings["promised_audio_missing"]["severity"] == "major"
    assert report["blockers"] == 0
    assert report["qualified"] is True
