from __future__ import annotations

import json
from pathlib import Path

from .evaluators import judge
from .schema import Brief, Concept


def select_joint_finalist(
    brief: Brief,
    sources: dict[str, Path],
    *,
    top_k_per_source: int = 8,
) -> dict:
    """Rejudge finalists from independent swarms in one shared population.

    Swarm-local totals include population-relative novelty, so winner totals from
    different runs are not directly comparable. This creates a single finalist
    population and recomputes every scorecard against the same competitors.
    """
    candidates: list[tuple[str, Concept, float, int]] = []
    for source, path in sources.items():
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        for row in rows[: max(1, top_k_per_source)]:
            concept = Concept.from_dict(row["concept"])
            original = float((row.get("scorecard") or {}).get("total", 0.0))
            original_rank = int(row.get("rank", len(candidates) + 1))
            candidates.append((source, concept, original, original_rank))

    if not candidates:
        raise ValueError("no finalist candidates found")

    # IDs are deterministic per originating provider/role. Deduplicate exact IDs
    # while retaining source provenance, then judge all finalists together.
    unique: list[tuple[str, Concept, float, int]] = []
    seen: set[str] = set()
    for row in candidates:
        if row[1].concept_id in seen:
            continue
        seen.add(row[1].concept_id)
        unique.append(row)

    population = [row[1] for row in unique]
    rescored = []
    for source, concept, original, original_rank in unique:
        scorecard = judge(concept, brief, population)
        rescored.append({
            "source": source,
            "concept": concept,
            "scorecard": scorecard,
            "original_score": original,
            "original_rank": original_rank,
        })
    rescored.sort(key=lambda row: row["scorecard"].total, reverse=True)
    winner = rescored[0]

    ranking = [
        {
            "rank": i + 1,
            "source": row["source"],
            "concept_id": row["concept"].concept_id,
            "title": row["concept"].title,
            "joint_score": row["scorecard"].total,
            "original_score": row["original_score"],
            "original_rank": row["original_rank"],
        }
        for i, row in enumerate(rescored)
    ]
    return {
        "source": winner["source"],
        "concept": winner["concept"],
        "scorecard": winner["scorecard"],
        "original_score": winner["original_score"],
        "original_rank": winner["original_rank"],
        "ranking": ranking,
        "candidate_count": len(rescored),
        "top_k_per_source": top_k_per_source,
    }


def write_joint_selection(
    brief: Brief,
    sources: dict[str, Path],
    output_dir: Path,
    *,
    top_k_per_source: int = 8,
) -> dict:
    selected = select_joint_finalist(brief, sources, top_k_per_source=top_k_per_source)
    output_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "source": selected["source"],
        "score": selected["scorecard"].total,
        "original_score": selected["original_score"],
        "original_rank": selected["original_rank"],
        "concept_id": selected["concept"].concept_id,
        "title": selected["concept"].title,
        "candidate_count": selected["candidate_count"],
        "top_k_per_source": selected["top_k_per_source"],
        "ranking": selected["ranking"],
        "score_scope": "joint-finalist-population",
    }
    (output_dir / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    (output_dir / "winner.json").write_text(json.dumps({
        "brief": brief.to_dict(),
        "concept": selected["concept"].to_dict(),
        "scorecard": selected["scorecard"].to_dict(),
        "selection": selection,
    }, indent=2) + "\n")
    return selection
