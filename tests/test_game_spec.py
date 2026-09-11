from game_engine.game_spec import compile_game_spec
from game_engine.schema import Brief, Concept
from game_engine.swarm import _roles_for_brief


def _concept():
    return Concept(
        concept_id="c1",
        title="Ghost Tether",
        hook="Swing a local echo with a rainbow tether.",
        core_mechanic="Orbit an anchor and transfer angular momentum through a rainbow tether so your partner sweeps targets.",
        player_goal="Land precise tether strikes and survive.",
        controls="Move to orbit; tap to pulse tether.",
        core_loop=["build momentum", "pulse tether", "recover"],
        escalation=["moving target", "reverse orbit"],
        visual_grammar="rainbow ribbon and horn trails",
        audio_grammar="tension pitch and impact plucks",
        category_fit=["desktop"],
        byte_hypothesis="Canvas and WebAudio primitives",
    )


def test_legacy_categories_migrate_to_one_active_primary_lane():
    brief = Brief(theme="x", target_categories=["desktop", "mobile", "online", "webxr"])
    assert brief.primary_category == "desktop"
    assert brief.expansion_categories == ["mobile", "online", "webxr"]
    assert brief.active_categories == ["desktop"]

    role_names = {role.name for role in _roles_for_brief(brief)}
    assert "desktop_specialist" in role_names
    assert "mobile_specialist" not in role_names
    assert "online_specialist" not in role_names
    assert "webxr_specialist" not in role_names


def test_native_hybrid_reenables_multiple_category_specialists():
    brief = Brief(
        theme="x",
        target_categories=["desktop", "online"],
        primary_category="desktop",
        expansion_categories=["online"],
        native_hybrid=True,
    )
    assert brief.active_categories == ["desktop", "online"]
    role_names = {role.name for role in _roles_for_brief(brief)}
    assert {"desktop_specialist", "online_specialist"} <= role_names


def test_game_spec_strips_expansion_work_from_first_prototype():
    brief = Brief(
        theme="Unicorns and Rainbows",
        primary_category="desktop",
        expansion_categories=["mobile", "online", "webxr"],
    )
    spec = compile_game_spec(brief, _concept())
    assert spec.primary_category == "desktop"
    assert spec.timing_contract["frame_rate_independent_damping"] is True
    assert spec.state_bounds["hazards_or_enemies"] > 0
    assert any("network" in item for item in spec.non_goals)
    assert any("online adaptation" in item for item in spec.non_goals)
    assert any("one arena" in item.lower() for item in spec.prototype_scope)
    assert "core_mechanic_activation" in spec.telemetry_contract["events"]
