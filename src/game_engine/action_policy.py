from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class InputProgramStep:
    action_id: str
    kind: str
    command: str
    binding: str | None = None
    direction: str | None = None
    duration_ms: int = 0
    sample_after: bool = False
    pointer_target: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionPlanError(ValueError):
    pass


def _required(action: dict[str, Any]) -> bool:
    return bool(action.get("required", True))


def _key_steps(action_id: str, key: str, hold_ms: int) -> list[InputProgramStep]:
    return [
        InputProgramStep(action_id, "key", "key_down", binding=key),
        InputProgramStep(action_id, "key", "wait", binding=key, duration_ms=hold_ms),
        InputProgramStep(action_id, "key", "key_up", binding=key, sample_after=True),
    ]


def _vector_steps(action: dict[str, Any], hold_ms: int) -> list[InputProgramStep]:
    action_id = str(action.get("id") or "move")
    bindings = action.get("bindings")
    if not isinstance(bindings, dict):
        raise ActionPlanError(f"{action_id}: keyboard_vector bindings must be an object")
    result: list[InputProgramStep] = []
    for direction in ("up", "left", "down", "right"):
        keys = bindings.get(direction)
        if not isinstance(keys, list) or not keys:
            if _required(action):
                raise ActionPlanError(f"{action_id}: missing {direction} binding")
            continue
        # Test every advertised alias separately. A builder that implements WASD but
        # silently ignores the advertised Arrow-key alias should be measurable.
        for key in keys:
            value = str(key)
            result.extend([
                InputProgramStep(action_id, "keyboard_vector", "key_down", binding=value, direction=direction),
                InputProgramStep(action_id, "keyboard_vector", "wait", binding=value, direction=direction, duration_ms=hold_ms),
                InputProgramStep(action_id, "keyboard_vector", "key_up", binding=value, direction=direction, sample_after=True),
            ])
    return result


def _pointer_click_steps(action_id: str) -> list[InputProgramStep]:
    return [
        InputProgramStep(action_id, "pointer_click", "pointer_click", pointer_target=(0.5, 0.5), sample_after=True),
    ]


def _pointer_drag_steps(action_id: str, hold_ms: int) -> list[InputProgramStep]:
    # Symmetric normalized trajectories are deterministic across viewport sizes.
    result: list[InputProgramStep] = []
    for label, target in (
        ("right", (0.75, 0.5)),
        ("left", (0.25, 0.5)),
        ("up", (0.5, 0.25)),
        ("down", (0.5, 0.75)),
    ):
        result.extend([
            InputProgramStep(action_id, "pointer_drag", "pointer_down", direction=label, pointer_target=(0.5, 0.5)),
            InputProgramStep(action_id, "pointer_drag", "pointer_move", direction=label, pointer_target=target, duration_ms=hold_ms),
            InputProgramStep(action_id, "pointer_drag", "pointer_up", direction=label, pointer_target=target, sample_after=True),
        ])
    return result


def compile_input_program(
    actions: list[dict[str, Any]],
    *,
    hold_ms: int = 160,
    max_actions: int = 3,
) -> list[InputProgramStep]:
    """Compile structured GameSpec actions into a reproducible browser-input program.

    Unsupported *required* actions fail closed. Optional unsupported actions are
    skipped. This keeps the executor honest as new Mobile/WebXR action kinds arrive.
    """
    if hold_ms < 20 or hold_ms > 2000:
        raise ActionPlanError("hold_ms must be between 20 and 2000")
    if len(actions) > max_actions:
        raise ActionPlanError(f"GameSpec declares {len(actions)} actions; max supported is {max_actions}")

    program: list[InputProgramStep] = []
    seen_ids: set[str] = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ActionPlanError(f"action[{index}] must be an object")
        action_id = str(action.get("id") or f"action_{index}")
        if action_id in seen_ids:
            raise ActionPlanError(f"duplicate action id: {action_id}")
        seen_ids.add(action_id)
        kind = str(action.get("kind") or "")

        if kind == "keyboard_vector":
            program.extend(_vector_steps(action, hold_ms))
        elif kind == "key":
            bindings = action.get("bindings")
            if not isinstance(bindings, list) or not bindings:
                raise ActionPlanError(f"{action_id}: key action requires bindings")
            for key in bindings:
                program.extend(_key_steps(action_id, str(key), hold_ms))
        elif kind == "pointer_click":
            program.extend(_pointer_click_steps(action_id))
        elif kind == "pointer_drag":
            program.extend(_pointer_drag_steps(action_id, hold_ms))
        elif _required(action):
            raise ActionPlanError(f"{action_id}: unsupported required action kind {kind!r}")

    return program


def action_boundaries(program: list[InputProgramStep]) -> list[dict[str, Any]]:
    """Return stable sample boundaries used to score each advertised action/binding."""
    boundaries: list[dict[str, Any]] = []
    for index, step in enumerate(program):
        if not step.sample_after:
            continue
        boundaries.append({
            "step_index": index,
            "action_id": step.action_id,
            "kind": step.kind,
            "binding": step.binding,
            "direction": step.direction,
        })
    return boundaries
