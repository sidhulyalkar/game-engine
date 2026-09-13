from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .portfolio_selection import concept_distance, select_concept_portfolio
from .progressive_portfolio import plan_progressive_prototypes
from .provider_performance import compile_provider_performance
from .schema import Brief, Concept


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise ValueError(f"required tournament artifact is missing: {path}")
    return json.loads(path.read_text())


def _leaderboard_sources(run_root: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for name in ("primary", "rescue"):
        path = run_root / f"swarm-{name}" / "leaderboard.json"
        if path.exists():
            sources[name] = path
    if not sources:
        raise ValueError(f"no swarm leaderboards found under {run_root}")
    return sources


def analyze_tournament_shadow(
    run_root: Path,
    output_path: Path | None = None,
    *,
    portfolio_size: int = 4,
    top_k_per_source: int = 12,
    min_distance: float = 0.28,
    initial_prototype_concepts: int = 2,
    max_builder_calls: int = 4,
) -> dict[str, Any]:
    """Analyze an already-paid-for tournament without changing routing or spending.

    The report answers three questions:
      1. Which mechanically distinct concepts did incumbent-only selection discard?
      2. Which provider phases actually produced usable artifacts/evidence?
      3. How could the same maximum builder-call budget buy more hypothesis breadth?

    It is deliberately shadow-only. No result here can promote a game, suppress a
    provider, or authorize a build.
    """
    run_root = Path(run_root)
    winner = _load_json(run_root / "champion" / "winner.json")
    brief = Brief.from_dict(winner["brief"])
    incumbent = Concept.from_dict(winner["concept"])
    selection_path = run_root / "champion" / "selection.json"
    selection = _load_json(selection_path) if selection_path.exists() else {}

    portfolio = select_concept_portfolio(
        brief,
        _leaderboard_sources(run_root),
        portfolio_size=portfolio_size,
        top_k_per_source=top_k_per_source,
        min_distance=min_distance,
        incumbent_concept_id=incumbent.concept_id,
    )
    progressive_plan = plan_progressive_prototypes(
        portfolio,
        initial_concepts=initial_prototype_concepts,
        max_total_builder_calls=max_builder_calls,
        confirmation_builds_per_survivor=1,
    )

    alternatives = []
    for row in portfolio["members"]:
        if row["concept_id"] == incumbent.concept_id:
            continue
        candidate = Concept.from_dict(row["concept"])
        distance = round(concept_distance(incumbent, candidate), 4)
        alternatives.append({
            "concept_id": row["concept_id"],
            "title": row["title"],
            "source": row["source"],
            "joint_score": row["joint_score"],
            "incumbent_distance": distance,
            "joint_score_gap_from_incumbent": round(
                float(selection.get("score", row["joint_score"])) - float(row["joint_score"]),
                4,
            ),
            "mechanic_descriptors": row["mechanic_descriptors"],
            "provenance": row["provenance"],
        })

    distances = [row["incumbent_distance"] for row in alternatives]
    provider_performance = compile_provider_performance(run_root)
    payload = {
        "schema_version": "0.2",
        "mode": "shadow",
        "routing_authority": False,
        "build_authority": False,
        "run_root": str(run_root),
        "incumbent": {
            "concept_id": incumbent.concept_id,
            "title": incumbent.title,
            "source": selection.get("source"),
            "joint_score": selection.get("score"),
        },
        "portfolio": portfolio,
        "progressive_prototype_plan": progressive_plan,
        "discarded_high_value_hypotheses": alternatives,
        "discarded_hypothesis_count": len(alternatives),
        "discarded_distance_summary": {
            "min_from_incumbent": min(distances) if distances else None,
            "max_from_incumbent": max(distances) if distances else None,
            "mean_from_incumbent": round(sum(distances) / len(distances), 4) if distances else None,
        },
        "provider_performance": provider_performance,
        "interpretation_boundary": (
            "Portfolio descriptors are preprototype lexical/mechanic proxies, provider "
            "performance is descriptive, and the progressive plan is only a spend "
            "counterfactual. None of these are gameplay quality or routing authority."
        ),
    }
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
