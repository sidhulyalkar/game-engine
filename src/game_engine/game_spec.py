from __future__ import annotations

import re
from typing import Any

from .schema import Brief, Concept, GameSpec


def _compact_sentence(value: str, max_words: int = 64) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _desktop_actions(controls: str) -> list[dict[str, Any]]:
    """Resolve compact control prose into <=3 deterministic Desktop actions.

    This is an Integrator decision, not free-form parsing. Exact named controls are
    preserved; underspecified common actions are normalized to a small conventional
    mapping so builders and behavioral probes share one authoritative contract.
    """
    text = re.sub(r"\s+", " ", controls).strip().lower()
    actions: list[dict[str, Any]] = []

    movement_words = ("move", "steer", "walk", "run", "orbit", "strafe", "drive", "slide")
    if "wasd" in text or "arrow" in text or any(word in text for word in movement_words):
        # Do not infer keyboard movement from phrases that clearly describe mouse
        # movement. This matters for mirrored-pointer games such as Prism Duet.
        mouse_movement = any(phrase in text for phrase in (
            "mouse move", "mouse moves", "move mouse", "move the mouse",
            "cursor move", "cursor moves", "move cursor", "move the cursor",
            "pointer move", "pointer moves", "move pointer", "move the pointer",
        ))
        if not mouse_movement or "wasd" in text or "arrow" in text:
            actions.append({
                "id": "move",
                "kind": "keyboard_vector",
                "bindings": {
                    "up": ["w", "ArrowUp"],
                    "left": ["a", "ArrowLeft"],
                    "down": ["s", "ArrowDown"],
                    "right": ["d", "ArrowRight"],
                },
                "semantics": "hold",
                "required": True,
                "source": "exact" if ("wasd" in text or "arrow" in text) else "integrator-default",
            })

    pointer_drag = any(phrase in text for phrase in (
        "mouse drag", "drag mouse", "drag the mouse", "pointer drag", "drag pointer",
        "drag the pointer", "cursor drag", "drag cursor", "drag the cursor",
    )) or ("drag" in text and any(word in text for word in ("mouse", "pointer", "cursor")))
    pointer_move = any(phrase in text for phrase in (
        "mouse move", "mouse moves", "move mouse", "move the mouse", "mouse aim", "aim with mouse",
        "cursor move", "cursor moves", "move cursor", "move the cursor", "aim with cursor",
        "pointer move", "pointer moves", "move pointer", "move the pointer", "aim with pointer",
    ))
    if pointer_drag:
        actions.append({
            "id": "pointer",
            "kind": "pointer_drag",
            "bindings": ["PrimaryPointer"],
            "semantics": "press-drag-release",
            "required": True,
            "source": "exact",
        })
    elif pointer_move:
        actions.append({
            "id": "pointer",
            "kind": "pointer_move",
            "bindings": ["PointerMotion"],
            "semantics": "move",
            "required": True,
            "source": "exact",
        })

    left_click = any(phrase in text for phrase in (
        "left click", "left-click", "primary click", "primary mouse", "primary button",
    ))
    right_click = any(phrase in text for phrase in (
        "right click", "right-click", "secondary click", "secondary mouse", "secondary button",
    ))
    generic_click = ("click" in text or "mouse button" in text) and not left_click and not right_click
    if left_click or generic_click:
        actions.append({
            "id": "primary",
            "kind": "pointer_click",
            "bindings": ["PrimaryPointer"],
            "semantics": "press",
            "required": True,
            "source": "exact",
        })
    if right_click:
        actions.append({
            "id": "secondary",
            "kind": "pointer_click",
            "bindings": ["SecondaryPointer"],
            "semantics": "press",
            "required": True,
            "source": "exact",
        })

    exact_keys = [
        ("space", "Space"),
        ("enter", "Enter"),
        ("shift", "Shift"),
    ]
    used_named_key = False
    for token, key in exact_keys:
        if token in text:
            actions.append({
                "id": "primary" if not used_named_key else f"action_{key.lower()}",
                "kind": "key",
                "bindings": [key],
                "semantics": "press",
                "required": True,
                "source": "exact",
            })
            used_named_key = True

    discrete_words = (
        "tap", "pulse", "fire", "shoot", "release", "jump", "dash", "slam",
        "swap", "flip", "reflect", "activate", "action",
    )
    already_has_discrete = any(action["kind"] in {"key", "pointer_click"} for action in actions)
    if not already_has_discrete and any(word in text for word in discrete_words):
        actions.append({
            "id": "primary",
            "kind": "key",
            "bindings": ["Space"],
            "semantics": "press",
            "required": True,
            "source": "integrator-default",
        })

    # Deduplicate semantically equivalent actions and preserve the <=3-action brief.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        signature = (str(action.get("kind")), json_signature(action.get("bindings")))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(action)
        if len(unique) >= 3:
            break
    return unique


def json_signature(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{key}:{json_signature(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(json_signature(item) for item in value) + "]"
    return str(value)


def compile_actions(primary_category: str, controls: str) -> list[dict[str, Any]]:
    if primary_category == "desktop":
        return _desktop_actions(controls)
    # Mobile/Online/WebXR action normalizers belong to their later adaptation lanes.
    return []


def compile_game_spec(brief: Brief, concept: Concept) -> GameSpec:
    """Compile a conservative first playable slice from a broader concept.

    This is intentionally deterministic. It gives builders an engineering contract
    without spending another remote inference call. A future Integrator agent can
    replace/refine this compiler while preserving the same artifact schema.
    """

    primary = brief.primary_category or "desktop"
    expansion_non_goals = [f"{category} adaptation" for category in brief.expansion_categories]
    category_specific_non_goals: list[str] = []
    if primary != "online":
        category_specific_non_goals.extend([
            "remote networking, fetch/post persistence, matchmaking, or leaderboards",
            "requiring another human player; use a deterministic local echo/AI if a partner is intrinsic",
        ])
    if primary != "webxr":
        category_specific_non_goals.append("WebXR session/controller/hand-tracking integration")
    if primary != "mobile":
        category_specific_non_goals.append("touch-specific UI beyond basic pointer compatibility")

    actions = compile_actions(primary, concept.controls)
    authoritative_controls = _compact_sentence(concept.controls, max_words=36)
    if actions:
        authoritative_controls += " GameSpec.actions is authoritative when prose is ambiguous."

    return GameSpec(
        spec_version="0.2",
        source_concept_id=concept.concept_id,
        title=concept.title,
        primary_category=primary,
        interaction_invariant=_compact_sentence(concept.core_mechanic, max_words=64),
        player_goal=_compact_sentence(concept.player_goal, max_words=36),
        controls=authoritative_controls,
        core_loop=[_compact_sentence(step, max_words=18) for step in concept.core_loop[:4]],
        prototype_scope=[
            "One arena and one complete playable run; prove the core interaction before breadth.",
            "At most one enemy/boss archetype plus one escalation rule in this slice.",
            "First meaningful player agency within 3 seconds after start/input unlock.",
            "Target a 30-60 second representative run with immediate restart.",
            "Do not implement meta progression, multiple levels, daily challenges, or category expansions.",
        ],
        state_machine={
            "states": ["playing", "dead", "won"],
            "start": "playing",
            "restart": "dead/won -> fresh playing state with score, timers, entities, and input state reset",
        },
        timing_contract={
            "simulation": "fixed-step 60 Hz accumulator or rigorously delta-time-scaled variable step",
            "delta_time_seconds": True,
            "max_frame_dt_seconds": 0.05,
            "frame_rate_independent_damping": True,
            "deterministic_seed": True,
        },
        state_bounds={
            "hazards_or_enemies": 32,
            "particles_or_trail_points": 256,
            "timers_or_scheduled_events": 32,
            "simultaneous_audio_voices": 16,
        },
        sensory_contract={
            "visual": _compact_sentence(concept.visual_grammar, max_words=45),
            "audio": _compact_sentence(concept.audio_grammar, max_words=45),
            "readability": "Core mechanic state, danger, success, and failure must be visible without reading debug text.",
        },
        telemetry_contract={
            "snapshot": [
                "elapsed_ms", "alive", "game_over", "score", "progress", "restart_count",
                "entity_count", "action_count", "last_action_ms", "state_hash",
            ],
            "events": [
                "run_start", "action_accepted", "progress_change", "damage_or_death",
                "restart", "core_mechanic_activation", "progression_transition",
            ],
        },
        byte_priorities=[
            "core interaction correctness and feel",
            "readable themed geometry and feedback",
            "procedural audio tied to state",
            "one escalation rule",
            "polish only after the above survive browser/play evidence",
        ],
        non_goals=list(dict.fromkeys([
            *category_specific_non_goals,
            *expansion_non_goals,
            "more than one enemy/boss archetype in the first prototype",
            "large shipped media assets",
            "code golf before gameplay qualification",
        ])),
        actions=actions,
    )
