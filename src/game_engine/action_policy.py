from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


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

    Unsupported required actions fail closed. Optional unsupported actions are skipped.
    This keeps the executor honest as later Mobile/WebXR action kinds arrive.
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


def _pixel_target(target: tuple[float, float] | None, width: int, height: int) -> tuple[int, int]:
    if target is None:
        raise ActionPlanError("pointer command is missing pointer_target")
    x, y = target
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ActionPlanError(f"normalized pointer target out of range: {target}")
    return int(round(x * width)), int(round(y * height))


def step_label(step: InputProgramStep) -> str:
    detail = step.binding or step.direction or ""
    suffix = f":{detail}" if detail else ""
    return f"{step.action_id}:{step.command}{suffix}"


def execute_input_program(
    page: Any,
    program: list[InputProgramStep],
    *,
    viewport_width: int,
    viewport_height: int,
    mark: Callable[[str], None] | None = None,
    sample: Callable[[], None] | None = None,
    settle_ms: int = 80,
) -> None:
    """Execute an abstract input program against a Playwright-like page.

    The function intentionally depends only on the page's keyboard/mouse/wait surface,
    making its choreography unit-testable without launching a browser. `sample()` is
    invoked only at explicit action boundaries so later scoring can attribute state
    changes to the advertised binding that preceded them.
    """
    if viewport_width <= 0 or viewport_height <= 0:
        raise ActionPlanError("viewport dimensions must be positive")
    if settle_ms < 0 or settle_ms > 5000:
        raise ActionPlanError("settle_ms must be between 0 and 5000")

    for step in program:
        if step.command == "key_down":
            if not step.binding:
                raise ActionPlanError(f"{step.action_id}: key_down missing binding")
            page.keyboard.down(step.binding)
        elif step.command == "key_up":
            if not step.binding:
                raise ActionPlanError(f"{step.action_id}: key_up missing binding")
            page.keyboard.up(step.binding)
        elif step.command == "wait":
            page.wait_for_timeout(step.duration_ms)
        elif step.command == "pointer_click":
            x, y = _pixel_target(step.pointer_target, viewport_width, viewport_height)
            page.mouse.click(x, y)
        elif step.command == "pointer_down":
            x, y = _pixel_target(step.pointer_target, viewport_width, viewport_height)
            page.mouse.move(x, y)
            page.mouse.down()
        elif step.command == "pointer_move":
            x, y = _pixel_target(step.pointer_target, viewport_width, viewport_height)
            page.mouse.move(x, y, steps=6)
            if step.duration_ms:
                page.wait_for_timeout(step.duration_ms)
        elif step.command == "pointer_up":
            x, y = _pixel_target(step.pointer_target, viewport_width, viewport_height)
            page.mouse.move(x, y)
            page.mouse.up()
        else:
            raise ActionPlanError(f"unsupported input program command: {step.command!r}")

        if mark is not None and step.command != "wait":
            mark(step_label(step))
        if step.sample_after:
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            if sample is not None:
                sample()
