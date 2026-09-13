from __future__ import annotations

from typing import Any


def plan_progressive_prototypes(
    portfolio: dict[str, Any],
    *,
    initial_concepts: int = 2,
    max_total_builder_calls: int = 4,
    confirmation_builds_per_survivor: int = 1,
) -> dict[str, Any]:
    """Allocate a fixed builder-call ceiling across breadth first, confirmation later.

    This planner is deliberately shadow-only. It does not choose a provider and it
    does not decide which prototype is better. It answers a narrower economic
    question: under a fixed maximum builder-call budget, how many distinct hypotheses
    should receive one cheap implementation before independent confirmation is bought?

    A concept earns confirmation only after deterministic source semantics plus the
    reference-browser/M4 gate. Expensive browser promotion and critics remain later.
    """
    members = [row for row in portfolio.get("members", []) if isinstance(row, dict)]
    if not members:
        raise ValueError("progressive prototype plan requires a non-empty portfolio")
    if initial_concepts < 1:
        raise ValueError("initial_concepts must be >= 1")
    if max_total_builder_calls < 1:
        raise ValueError("max_total_builder_calls must be >= 1")
    if confirmation_builds_per_survivor < 0:
        raise ValueError("confirmation_builds_per_survivor must be >= 0")

    initial_count = min(initial_concepts, len(members), max_total_builder_calls)
    selected = members[:initial_count]
    initial_calls = initial_count
    remaining_calls = max_total_builder_calls - initial_calls
    max_confirmed_survivors = (
        remaining_calls // confirmation_builds_per_survivor
        if confirmation_builds_per_survivor > 0
        else 0
    )

    slots = []
    for row in selected:
        slots.append({
            "slot": int(row.get("slot", len(slots) + 1)),
            "concept_id": str(row.get("concept_id")),
            "title": str(row.get("title")),
            "is_incumbent": bool(row.get("is_incumbent")),
            "joint_score": row.get("joint_score"),
            "nearest_prior_distance": row.get("nearest_prior_distance"),
            "initial_builder_calls": 1,
            "confirmation_eligible_after": [
                "source_semantics",
                "reference_browser",
                "causal_controls",
                "restart_integrity",
                "independent_pixels",
            ],
        })

    incumbent_ids = [row["concept_id"] for row in slots if row["is_incumbent"]]
    return {
        "schema_version": "0.1",
        "mode": "shadow",
        "build_authority": False,
        "routing_authority": False,
        "portfolio_size_available": len(members),
        "initial_concepts": len(slots),
        "initial_builder_calls": initial_calls,
        "max_total_builder_calls": max_total_builder_calls,
        "remaining_confirmation_calls": remaining_calls,
        "confirmation_builds_per_survivor": confirmation_builds_per_survivor,
        "max_confirmed_survivors": max_confirmed_survivors,
        "incumbent_present": bool(incumbent_ids),
        "incumbent_concept_ids": incumbent_ids,
        "slots": slots,
        "spend_policy": (
            "breadth-first one-build hypotheses; confirmation only after semantic and "
            "reference-browser causal gameplay qualification"
        ),
        "downstream_policy": (
            "Firefox/WebKit and subjective critics are purchased only after confirmation "
            "or when the configured experiment explicitly waives confirmation"
        ),
    }
