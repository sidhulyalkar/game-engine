import pytest

from game_engine.action_policy import (
    ActionPlanError,
    action_boundaries,
    compile_input_program,
    execute_input_program,
)
from game_engine.game_spec import compile_actions


def test_desktop_actions_compile_to_labeled_press_hold_release_program():
    actions = compile_actions("desktop", "WASD to move and Space to dash")
    program = compile_input_program(actions, hold_ms=120)
    boundaries = action_boundaries(program)

    move = [row for row in boundaries if row["action_id"] == "move"]
    primary = [row for row in boundaries if row["action_id"] == "primary"]
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


def test_prism_actions_compile_pointer_motion_and_left_right_click_boundaries():
    actions = compile_actions(
        "desktop",
        "Mouse moves mirrored echoes; left click detonate; right click flip polarity.",
    )
    program = compile_input_program(actions, hold_ms=100)
    boundaries = action_boundaries(program)
    pointer = [row for row in boundaries if row["action_id"] == "pointer"]
    primary = [row for row in boundaries if row["action_id"] == "primary"]
    secondary = [row for row in boundaries if row["action_id"] == "secondary"]
    assert len(pointer) == 4
    assert [row["direction"] for row in pointer] == ["right", "left", "up", "down"]
    assert primary[0]["binding"] == "PrimaryPointer"
    assert secondary[0]["binding"] == "SecondaryPointer"
    assert all(step.command != "pointer_down" for step in program if step.action_id == "pointer")


def test_executor_sends_secondary_click_and_passive_motion_without_mouse_down():
    actions = compile_actions(
        "desktop",
        "Mouse moves mirrored echoes; left click detonate; right click flip polarity.",
    )
    program = compile_input_program(actions, hold_ms=40)
    calls = []
    marks = []
    samples = []

    class Keyboard:
        def down(self, key):
            calls.append(("key_down", key))

        def up(self, key):
            calls.append(("key_up", key))

    class Mouse:
        def move(self, x, y, **kwargs):
            calls.append(("move", x, y, kwargs))

        def click(self, x, y, **kwargs):
            calls.append(("click", x, y, kwargs))

        def down(self, **kwargs):
            calls.append(("down", kwargs))

        def up(self, **kwargs):
            calls.append(("up", kwargs))

    class Page:
        keyboard = Keyboard()
        mouse = Mouse()

        def wait_for_timeout(self, duration):
            calls.append(("wait", duration))

    execute_input_program(
        Page(),
        program,
        viewport_width=800,
        viewport_height=600,
        mark=marks.append,
        sample=lambda: samples.append("sample"),
        settle_ms=0,
    )

    assert not any(call[0] == "down" for call in calls)
    clicks = [call for call in calls if call[0] == "click"]
    assert clicks[0][3]["button"] == "left"
    assert clicks[1][3]["button"] == "right"
    moves = [call for call in calls if call[0] == "move"]
    assert [(row[1], row[2]) for row in moves[:4]] == [(600, 300), (200, 300), (400, 150), (400, 450)]
    assert len(samples) == len(action_boundaries(program))
    assert any("secondary:pointer_click:SecondaryPointer" in mark for mark in marks)


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
