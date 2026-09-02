from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .evaluators import judge, token_jaccard
from .schema import Brief, Concept


# This vocabulary is intentionally coarse. It is not a game-quality evaluator. It is
# only a cheap preprototype description that prevents the build budget from collapsing
# onto several prose variants of the same interaction family. Once browser play traces
# exist, behavioral descriptors should replace these lexical proxies.
_MECHANIC_TERMS = (
    "orbit", "tether", "spring", "stretch", "slingshot", "charge", "release",
    "paint", "draw", "trail", "territory", "route", "rail", "grind", "steer",
    "dodge", "dash", "collision", "bounce", "reflect", "parry", "projectile",
    "rhythm", "beat", "timing", "aim", "shoot", "herd", "escort", "collect",
    "survive", "puzzle", "race", "platform", "physics", "momentum", "gravity",
)
_CONTROL_TERMS = (
    "wasd", "arrow", "mouse", "pointer", "click", "drag", "hold", "release",
    "space", "keyboard", "tap", "touch", "move", "aim",
)


@dataclass(slots=True)
class PortfolioCandidate:
    source: str
    concept: Concept
    joint_score: float
    original_score: float
    original_rank: int
    descriptors: set[str]


def _text(concept: Concept) -> str:
    return " ".join([
        concept.title,
        concept.hook,
        concept.core_mechanic,
        concept.player_goal,
        concept.controls,
        *concept.core_loop,
        *concept.escalation,
        *concept.tags,
    ]).lower()


def concept_descriptors(concept: Concept) -> set[str]:
    text = _text(concept)
    descriptors = {f"tag:{str(tag).lower()}" for tag in concept.tags if str(tag).strip()}
    for term in _MECHANIC_TERMS:
        if re.search(rf"\b{re.escape(term)}\w*\b", text):
            descriptors.add(f"mechanic:{term}")
    controls = concept.controls.lower()
    for term in _CONTROL_TERMS:
        if re.search(rf"\b{re.escape(term)}\w*\b", controls):
            descriptors.add(f"control:{term}")
    descriptors.update(f"category:{value.lower()}" for value in concept.category_fit)
    return descriptors


def descriptor_jaccard(a: Concept, b: Concept) -> float:
    da = concept_descriptors(a)
    db = concept_descriptors(b)
    if not da or not db:
        return 0.0
    return len(da & db) / len(da | db)


def concept_distance(a: Concept, b: Concept) -> float:
    """Conservative preprototype diversity distance in [0,1].

    We combine lexical overlap with coarse mechanic/control descriptors. Using the
    maximum similarity makes near-duplicates difficult to sneak through merely by
    changing nouns while preserving the same interaction topology.
    """
    similarity = max(token_jaccard(a, b), descriptor_jaccard(a, b))
    return max(0.0, min(1.0, 1.0 - similarity))


def _load_joint_candidates(
    brief: Brief,
    sources: dict[str, Path],
    top_k_per_source: int,
) -> list[PortfolioCandidate]:
    raw: list[tuple[str, Concept, float, int]] = []
    for source, path in sources.items():
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        for row in rows[: max(1, top_k_per_source)]:
            concept = Concept.from_dict(row["concept"])
            raw.append((
                source,
                concept,
                float((row.get("scorecard") or {}).get("total", 0.0)),
                int(row.get("rank", len(raw) + 1)),
            ))
    if not raw:
        raise ValueError("no finalist candidates found")

    unique: list[tuple[str, Concept, float, int]] = []
    seen: set[str] = set()
    for row in raw:
        if row[1].concept_id in seen:
            continue
        seen.add(row[1].concept_id)
        unique.append(row)

    population = [row[1] for row in unique]
    candidates = []
    for source, concept, original, original_rank in unique:
        scorecard = judge(concept, brief, population)
        candidates.append(PortfolioCandidate(
            source=source,
            concept=concept,
            joint_score=scorecard.total,
            original_score=original,
            original_rank=original_rank,
            descriptors=concept_descriptors(concept),
        ))
    candidates.sort(key=lambda row: (-row.joint_score, row.concept.concept_id))
    return candidates


def select_concept_portfolio(
    brief: Brief,
    sources: dict[str, Path],
    *,
    portfolio_size: int = 4,
    top_k_per_source: int = 12,
    min_distance: float = 0.28,
    diversity_weight: float = 0.45,
) -> dict:
    """Select a diverse build portfolio without pretending prose scores prove quality.

    The highest joint-scoring concept earns the first prototype. Remaining slots use
    greedy max-min diversity plus a bounded quality prior. Candidates inside the hard
    near-duplicate radius are skipped while alternatives exist. If the pool cannot fill
    the requested size under that constraint, the selector relaxes only for the final
    unfilled slots and records that fact explicitly.
    """
    if portfolio_size < 1:
        raise ValueError("portfolio_size must be >= 1")
    if not 0 <= min_distance <= 1:
        raise ValueError("min_distance must be between 0 and 1")
    if not 0 <= diversity_weight <= 1:
        raise ValueError("diversity_weight must be between 0 and 1")

    candidates = _load_joint_candidates(brief, sources, top_k_per_source)
    selected: list[PortfolioCandidate] = [candidates[0]]
    remaining = candidates[1:]
    relaxed = False

    score_values = [row.joint_score for row in candidates]
    low, high = min(score_values), max(score_values)

    def quality(row: PortfolioCandidate) -> float:
        if high <= low:
            return 1.0
        return (row.joint_score - low) / (high - low)

    while remaining and len(selected) < min(portfolio_size, len(candidates)):
        scored = []
        for row in remaining:
            minimum_distance = min(concept_distance(row.concept, keep.concept) for keep in selected)
            utility = (1.0 - diversity_weight) * quality(row) + diversity_weight * minimum_distance
            scored.append((minimum_distance >= min_distance, utility, minimum_distance, row))

        eligible = [entry for entry in scored if entry[0]]
        field = eligible if eligible else scored
        if not eligible:
            relaxed = True
        _, _, _, winner = max(
            field,
            key=lambda entry: (entry[1], entry[2], entry[3].joint_score, entry[3].concept.concept_id),
        )
        selected.append(winner)
        remaining = [row for row in remaining if row.concept.concept_id != winner.concept.concept_id]

    rows = []
    for index, row in enumerate(selected):
        nearest = None if index == 0 else min(
            concept_distance(row.concept, prior.concept) for prior in selected[:index]
        )
        rows.append({
            "slot": index + 1,
            "source": row.source,
            "concept_id": row.concept.concept_id,
            "title": row.concept.title,
            "joint_score": row.joint_score,
            "original_score": row.original_score,
            "original_rank": row.original_rank,
            "nearest_prior_distance": round(nearest, 4) if nearest is not None else None,
            "descriptors": sorted(row.descriptors),
            "concept": row.concept.to_dict(),
        })

    return {
        "portfolio_size_requested": portfolio_size,
        "portfolio_size_selected": len(rows),
        "candidate_count": len(candidates),
        "top_k_per_source": top_k_per_source,
        "min_distance": min_distance,
        "diversity_weight": diversity_weight,
        "distance_constraint_relaxed": relaxed,
        "selection_role": "preprototype build-budget allocation only",
        "members": rows,
    }


def write_concept_portfolio(
    brief: Brief,
    sources: dict[str, Path],
    output_dir: Path,
    **kwargs,
) -> dict:
    result = select_concept_portfolio(brief, sources, **kwargs)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "portfolio.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
