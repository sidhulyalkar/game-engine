from __future__ import annotations

import re

from .schema import Brief, Concept, GameSpec


def _compact_sentence(value: str, max_words: int = 64) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


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

    return GameSpec(
        spec_version="0.1",
        source_concept_id=concept.concept_id,
        title=concept.title,
        primary_category=primary,
        interaction_invariant=_compact_sentence(concept.core_mechanic, max_words=64),
        player_goal=_compact_sentence(concept.player_goal, max_words=36),
        controls=_compact_sentence(concept.controls, max_words=36),
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
    )
