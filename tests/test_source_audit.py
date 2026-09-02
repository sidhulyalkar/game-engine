import json

from game_engine.schema import Brief, Concept
from game_engine.source_audit import AuditFinding, CriticAudit, _filter_browser_qualified, aggregate_audits, auditor_prompt


def audit(provider, verdict, score=8.0, findings=None):
    dims = {
        "concept_fidelity": score,
        "logic_correctness": score,
        "first_10s_clarity": score,
        "game_feel": score,
        "mastery_curve": score,
        "pacing_progression": score,
        "visual_identity": score,
        "audio_feedback": score,
        "replayability": score,
        "exploit_resistance": score,
    }
    return CriticAudit(provider=provider, build_id="abc", ok=True, scores=dims, verdict=verdict, findings=findings or [])


def concept():
    return Concept(
        concept_id="c1",
        title="Slow Hazard",
        hook="Dodge a hazard.",
        core_mechanic="A hazard crosses the arena while the player redirects it.",
        player_goal="Survive.",
        controls="Mouse moves; click redirects.",
        core_loop=["move", "redirect"],
        escalation=["faster hazards"],
        visual_grammar="simple arena",
        audio_grammar="impact clicks",
        category_fit=["desktop"],
        byte_hypothesis="Canvas primitives",
    )


def test_two_clean_critics_can_advance():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "advance"), audit("b", "advance", 7.6)],
    )
    assert result.status == "advance"
    assert result.blockers == 0
    assert result.critic_count == 2


def test_blocker_prevents_advance():
    blocker = AuditFinding("blocker", "logic", "cleanup compares object to number", "entities leak", "compare y to height")
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "repair", findings=[blocker]), audit("b", "advance")],
    )
    assert result.status == "repair"
    assert result.blockers == 1


def test_no_successful_critics_rejects():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [CriticAudit(provider="a", build_id="abc", ok=False, error="timeout")],
    )
    assert result.status == "reject"
    assert result.critic_count == 0


def test_browser_qualification_filters_expensive_critic_field(tmp_path):
    reality = tmp_path / "reality"
    reality.mkdir()
    (reality / "qualification.json").write_text(json.dumps({"full_pass_build_ids": ["keep"]}))
    builds = [
        {"build_id": "keep", "provider": "a"},
        {"build_id": "drop", "provider": "b"},
    ]
    assert _filter_browser_qualified(builds, reality) == [{"build_id": "keep", "provider": "a"}]


def test_auditor_prompt_includes_gamespec_and_seconds_to_effect_contract():
    game_spec = {
        "prototype_scope": ["Target a 30-60 second representative run."],
        "timing_contract": {"delta_time_seconds": True},
        "actions": [{"id": "pointer", "kind": "pointer_move"}],
    }
    html = "<canvas width=640 height=480></canvas><script>e.y += .75 * dt</script>"
    _, prompt = auditor_prompt(
        Brief(theme="Unicorns and Rainbows"),
        concept(),
        {"build_id": "abc", "provider": "builder"},
        html,
        [],
        game_spec=game_spec,
    )
    assert "DETERMINISTIC IMPLEMENTATION GAMESPEC" in prompt
    assert "30-60 second" in prompt
    assert "time-scale sanity audit" in prompt
    assert "distance / pixels-per-second" in prompt
    assert "rate * dt_seconds" in prompt
    assert "GameSpec.actions" in prompt
    assert "e.y += .75 * dt" in prompt
