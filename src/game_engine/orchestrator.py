from __future__ import annotations

import json
from pathlib import Path

from .evaluators import deduplicate, judge, mechanic_distribution
from .idea_space import mutate, procedural_concepts
from .schema import Brief, Concept, ScoreCard


class Studio:
    """Deterministic evolutionary core. LLM adapters can be layered on without changing artifact contracts."""

    def __init__(self, seed: int = 13):
        self.seed = seed

    def ideate(self, brief: Brief, count: int = 24, finalists: int = 6, mutations_per_finalist: int = 2) -> tuple[list[Concept], list[ScoreCard]]:
        population = deduplicate(procedural_concepts(brief, count=count, seed=self.seed))
        scored = [judge(c, brief, population) for c in population]
        score_by_id = {s.concept_id: s for s in scored}
        parents = sorted(population, key=lambda c: score_by_id[c.concept_id].total, reverse=True)[:finalists]

        mutants: list[Concept] = []
        idx = 0
        for parent in parents:
            for _ in range(mutations_per_finalist):
                mutants.append(mutate(parent, self.seed + 1, idx))
                idx += 1
        population = deduplicate(population + mutants)
        scored = [judge(c, brief, population) for c in population]
        scored.sort(key=lambda s: s.total, reverse=True)
        concept_map = {c.concept_id: c for c in population}
        ranked = [concept_map[s.concept_id] for s in scored]
        return ranked, scored

    def run(self, brief: Brief, output_dir: Path, count: int = 24) -> dict:
        concepts, scores = self.ideate(brief, count=count)
        output_dir.mkdir(parents=True, exist_ok=True)
        score_map = {s.concept_id: s for s in scores}
        winner = concepts[0]
        manifest = {
            "engine_version": "0.1.0",
            "seed": self.seed,
            "brief": brief.to_dict(),
            "population_size": len(concepts),
            "mechanic_distribution": mechanic_distribution(concepts),
            "winner_id": winner.concept_id,
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (output_dir / "leaderboard.json").write_text(json.dumps([
            {"rank": i + 1, "concept": c.to_dict(), "scorecard": score_map[c.concept_id].to_dict()}
            for i, c in enumerate(concepts)
        ], indent=2) + "\n")
        (output_dir / "winner.json").write_text(json.dumps({
            "brief": brief.to_dict(),
            "concept": winner.to_dict(),
            "scorecard": score_map[winner.concept_id].to_dict(),
        }, indent=2) + "\n")
        (output_dir / "STUDIO_BRIEF.md").write_text(self._studio_brief(winner, score_map[winner.concept_id], brief))
        return manifest

    @staticmethod
    def _studio_brief(concept: Concept, score: ScoreCard, brief: Brief) -> str:
        loop = "\n".join(f"{i+1}. {step}" for i, step in enumerate(concept.core_loop))
        escalation = "\n".join(f"- {step}" for step in concept.escalation)
        return f"""# {concept.title}\n\n> {concept.hook}\n\n## North star\n\n**Goal:** {concept.player_goal}\n\n**Core mechanic:** {concept.core_mechanic}\n\n**Controls:** {concept.controls}\n\n## Player loop\n\n{loop}\n\n## Escalation\n\n{escalation}\n\n## Sensory grammar\n\n- Visual: {concept.visual_grammar}\n- Audio: {concept.audio_grammar}\n\n## Byte architecture\n\n{concept.byte_hypothesis}\n\nTarget compressed package: **{brief.size_limit_bytes} bytes or less**.\n\n## Judge panel\n\nOverall static concept score: **{score.total}/10**\n\n""" + "\n".join(f"- {k}: {v}/10" for k, v in score.scores.items()) + "\n"
