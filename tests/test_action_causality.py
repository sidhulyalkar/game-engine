from game_engine.action_causality import _pointer_setup_step, assess_action_trial, split_action_trials
from game_engine.action_policy import compile_input_program


def snapshot(**overrides):
    row = {
        "elapsed_ms": 100.0,
        "tick": 0,
        "state": "playing",
        "alive": True,
        "game_over": False,
        "score": 0,
        "progress": 0.0,
        "restart_count": 0,
        "entity_count": 1,
        "action_count": 0,
        "last_action_ms": None,
        "core_mechanic_activations": 0,
        "progression_transitions": 0,
        "state_hash": "fresh",
    }
    row.update(overrides)
    return row


def test_input_program_splits_every_binding_direction_into_fresh_trial():
    actions = [
        {
            "id": "move",
            "kind": "keyboard_vector",
            "bindings": {
                "up": ["w", "ArrowUp"],
                "left": ["a", "ArrowLeft"],
                "down": ["s", "ArrowDown"],
                "right": ["d", "ArrowRight"],
            },
            "required": True,
        },
        {"id": "primary", "kind": "key", "bindings": ["Space"], "required": True},
    ]
    trials = split_action_trials(compile_input_program(actions, hold_ms=120))
    assert len(trials) == 9
    assert all(trial[-1].sample_after for trial in trials)
    assert [trial[-1].binding for trial in trials[:2]] == ["w", "ArrowUp"]
    assert trials[-1][-1].action_id == "primary"
    assert trials[-1][-1].binding == "Space"


def test_pointer_click_setup_is_preconditioned_but_pointer_motion_is_not():
    actions = [
        {"id": "aim", "kind": "pointer_move", "required": True},
        {"id": "primary", "kind": "pointer_click", "bindings": ["PrimaryPointer"], "required": True},
    ]
    trials = split_action_trials(compile_input_program(actions, hold_ms=120))
    motion_trial = next(trial for trial in trials if trial[-1].action_id == "aim")
    click_trial = next(trial for trial in trials if trial[-1].action_id == "primary")
    assert _pointer_setup_step(motion_trial) is None
    setup = _pointer_setup_step(click_trial)
    assert setup is not None
    assert setup.pointer_target == (0.5, 0.5)


def test_acknowledged_but_bookkeeping_only_input_is_rejected():
    before = snapshot()
    after = snapshot(elapsed_ms=180.0, action_count=1, last_action_ms=140.0)
    ok, accepted, meaningful, visible, violations, warnings = assess_action_trial(
        before,
        after,
        before_events=[],
        after_events=[{"type": "action_accepted"}],
        before_visible_hash="same",
        after_visible_hash="same",
        required=True,
    )
    assert ok is False
    assert accepted is True
    assert meaningful is False
    assert visible is False
    assert "required advertised binding produced no causal gameplay effect beyond matched idle" in violations
    assert "input was acknowledged but only bookkeeping or matched-idle effects changed" in warnings


def test_self_reported_core_activation_and_state_hash_cannot_certify_effect():
    before = snapshot()
    after = snapshot(
        elapsed_ms=180.0,
        action_count=1,
        last_action_ms=140.0,
        core_mechanic_activations=1,
        state_hash="claimed-effect",
    )
    ok, accepted, meaningful, visible, violations, warnings = assess_action_trial(
        before,
        after,
        before_events=[],
        after_events=[{"type": "action_accepted"}, {"type": "core_mechanic_activation"}],
        before_visible_hash="same",
        after_visible_hash="same",
        required=True,
    )
    assert ok is False
    assert accepted is True
    assert meaningful is False
    assert visible is False
    assert "required advertised binding produced no causal gameplay effect beyond matched idle" in violations
    assert "input was acknowledged but only bookkeeping or matched-idle effects changed" in warnings


def test_real_state_and_pixel_effect_passes_required_binding():
    before = snapshot()
    after = snapshot(
        elapsed_ms=180.0,
        action_count=1,
        last_action_ms=140.0,
        score=10,
        core_mechanic_activations=1,
        state_hash="fired",
    )
    ok, accepted, meaningful, visible, violations, warnings = assess_action_trial(
        before,
        after,
        before_events=[],
        after_events=[{"type": "action_accepted"}, {"type": "core_mechanic_activation"}],
        before_visible_hash="before",
        after_visible_hash="after",
        required=True,
    )
    assert ok is True
    assert accepted is True
    assert meaningful is True
    assert visible is True
    assert violations == []
    assert warnings == []


def test_matched_idle_score_drift_is_subtracted_but_larger_active_delta_survives():
    before = snapshot(score=0)
    active_after = snapshot(score=10, action_count=1)
    control_before = snapshot(score=0)
    control_after = snapshot(score=1)
    ok, accepted, meaningful, visible, violations, warnings = assess_action_trial(
        before,
        active_after,
        before_events=[],
        after_events=[{"type": "action_accepted"}],
        before_visible_hash="same",
        after_visible_hash="same",
        required=True,
        control_before=control_before,
        control_after=control_after,
        control_before_visible_hash="idle-a",
        control_after_visible_hash="idle-a",
    )
    assert ok is True
    assert accepted is True
    assert meaningful is True
    assert visible is False
    assert violations == []
    assert "matched idle trial changed gameplay state; active effect was baseline-subtracted" in warnings


def test_identical_active_and_idle_progress_is_not_causal():
    before = snapshot(progress=0.0)
    active_after = snapshot(progress=0.1, action_count=1)
    control_before = snapshot(progress=0.0)
    control_after = snapshot(progress=0.1)
    ok, accepted, meaningful, visible, violations, warnings = assess_action_trial(
        before,
        active_after,
        before_events=[],
        after_events=[{"type": "action_accepted"}],
        before_visible_hash="frame-a",
        after_visible_hash="frame-b",
        required=True,
        control_before=control_before,
        control_after=control_after,
        control_before_visible_hash="idle-a",
        control_after_visible_hash="idle-b",
    )
    assert ok is False
    assert accepted is True
    assert meaningful is False
    assert visible is False
    assert "required advertised binding produced no causal gameplay effect beyond matched idle" in violations
    assert "matched idle trial changed pixels; visual change alone cannot certify this action" in warnings


def test_active_visual_change_counts_when_matched_idle_is_stable():
    before = snapshot()
    active_after = snapshot(action_count=1)
    control_before = snapshot()
    control_after = snapshot()
    ok, accepted, meaningful, visible, violations, _ = assess_action_trial(
        before,
        active_after,
        before_events=[],
        after_events=[{"type": "action_accepted"}],
        before_visible_hash="frame-a",
        after_visible_hash="frame-b",
        required=True,
        control_before=control_before,
        control_after=control_after,
        control_before_visible_hash="idle-a",
        control_after_visible_hash="idle-a",
    )
    assert ok is True
    assert accepted is True
    assert meaningful is False
    assert visible is True
    assert violations == []


def test_unaccepted_required_binding_is_rejected_even_if_idle_animation_changes_pixels():
    before = snapshot()
    after = snapshot(elapsed_ms=180.0)
    ok, accepted, meaningful, visible, violations, _ = assess_action_trial(
        before,
        after,
        before_events=[],
        after_events=[],
        before_visible_hash="frame-a",
        after_visible_hash="frame-b",
        required=True,
    )
    assert ok is False
    assert accepted is False
    assert meaningful is False
    assert visible is True
    assert "required advertised binding was not accepted by gameplay" in violations
