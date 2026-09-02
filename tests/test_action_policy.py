import pytest

from game_engine.action_policy import ActionPlanError, action_boundaries, compile_input_program
from game_engine.game_spec import compile_actions


def test_desktop_actions_compile_to_labeled_press_hold_release_program():
    actions = compile_actions("desktop", "WASD to move and Space to dash")
    program = compile_input_program(actions, hold_ms=120)
    boundaries = action_boundaries(program)

    move = [row for row in boundaries if row["action_id"] == "move"]
    primary = [row for row in boundaries if row["action_id"] == "primary"]
    # WASD + Arrow aliases are each tested independently in four directions.
    assert len(move) == 8
    assert {row["direction"] for row in move} == {"up", "left", "down", "right"}
    assert {row["binding"] for row in move} == {
        "w", "a", "s", "d", "ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"
    }
    assert primary == [{
        "step_index": len(program) - 1,
        "action_id": "primary",
        "kind": "key",
        "binding": "Space",
        "direction": None,
    }]
    assert any(step.command == "wait" and step.duration_ms == 120 for step in program)


def test_pointer_drag_program_uses_viewport_normalized_deterministic_targets():
    actions = compile_actions("desktop", "mouse drag to aim")
    program = compile_input_program(actions)
    boundaries = action_boundaries(program)
    assert len(boundaries) == 4
    assert [row["direction"] for row in boundaries] == ["right", "left", "up", "down"]
    targets = [step.pointer_target for step in program if step.command == "pointer_move"]
    assert targets == [(0.75, 0.5), (0.25, 0.5), (0.5, 0.25), (0.5, 0.75)]


def test_required_unknown_action_kind_fails_closed():
    with pytest.raises(ActionPlanError, match="unsupported required action"):
        compile_input_program([{"id": "grab", "kind": "webxr_grab", "required": True}])


def test_optional_unknown_action_kind_can_be_skipped():
    assert compile_input_program([{"id": "decorative", "kind": "future_kind", "required": False}]) == []


def test_duplicate_action_ids_and_action_budget_fail_closed():
    with pytest.raises(ActionPlanError, match="duplicate action id"):
        compile_input_program([
            {"id": "primary", "kind": "key", "bindings": ["Space"]},
            {"id": "primary", "kind": "key", "bindings": ["Enter"]},
        ])
    with pytest.raises(ActionPlanError, match="max supported"):
        compile_input_program([
            {"id": "a", "kind": "key", "bindings": ["1"]},
            {"id": "b", "kind": "key", "bindings": ["2"]},
            {"id": "c", "kind": "key", "bindings": ["3"]},
            {"id": "d", "kind": "key", "bindings": ["4"]},
        ])
