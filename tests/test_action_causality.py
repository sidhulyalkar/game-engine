from game_engine.action_causality import assess_action_trial, split_action_trials
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
    assert "required advertised binding produced no meaningful gameplay effect" in violations
    assert "input was acknowledged but only bookkeeping changed" in warnings


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
