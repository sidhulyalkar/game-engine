import json
from dataclasses import dataclass

from game_engine.agents import STUDIO_ROLES
from game_engine.prompts import REVIEW_SYSTEM, reviewer_prompt
from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio
from game_engine.swarm_health import contribution_summary


@dataclass
class JudgeSpec:
    name: str = "judge-provider"
    roles: tuple[str, ...] = ("competition_judge",)
    max_concurrency: int = 1


class JudgeClient:
    name = "judge-provider"

    def __init__(self):
        self.system = None
        self.prompt = None

    def complete(self, system, prompt):
        self.system = system
        self.prompt = prompt
        marker = "CANDIDATE CONCEPTS TO JUDGE:\n"
        body = prompt.split(marker, 1)[1].split("\n\nEvaluate these candidates only.", 1)[0]
        candidates = json.loads(body)
        ids = [row["id"] for row in candidates]
        return json.dumps({
            "review": {
                "reviewed_ids": ids,
                "winner_id": ids[0],
                "ranking": [
                    {
                        "id": concept_id,
                        "score": 9.0 - index,
                        "reason": "Distinct mechanic with plausible first-minute mastery and compact implementation.",
                    }
                    for index, concept_id in enumerate(ids)
                ],
                "fatal_risks": ["Control readability needs testing."],
                "summary": "The first candidate best balances novelty, readable agency, escalation, and byte-feasible procedural presentation.",
            }
        })


def test_competition_judge_role_is_review_native():
    role = next(role for role in STUDIO_ROLES if role.name == "competition_judge")
    assert role.mode == "review"
    assert "Score innovation" in role.mission


def test_reviewer_prompt_explicitly_forbids_concept_invention():
    brief = Brief(theme="Unicorns and Rainbows")
    seeds = []
    prompt = reviewer_prompt(
        next(role for role in STUDIO_ROLES if role.name == "competition_judge"),
        brief,
        seeds,
    )
    assert "Do NOT generate a replacement concept" in prompt
    assert "Evaluate these candidates only" in prompt
    assert "Do not invent" in REVIEW_SYSTEM


def test_judge_review_satisfies_role_evidence_without_expanding_population():
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    client = JudgeClient()
    concepts, scores, contributions = SwarmStudio(
        [(JudgeSpec(), client)], seed=13, max_workers=1
    ).ideate(brief, deterministic_seeds=4, concepts_per_call=3)

    assert len(concepts) == 4, "review role must not create replacement concepts"
    assert len(scores) == 4
    assert len(contributions) == 1
    row = contributions[0]
    assert row.ok is True
    assert row.role == "competition_judge"
    assert row.evidence_kind == "concept_review"
    assert row.concept_ids == []
    assert len(row.reviewed_concept_ids) == 4
    assert row.review["winner_id"] == row.review["ranking"][0]["id"]
    assert client.system == REVIEW_SYSTEM
    assert "Generate exactly" not in client.prompt

    health = contribution_summary(
        [
            {
                "provider": row.provider,
                "role": row.role,
                "ok": row.ok,
                "concept_ids": row.concept_ids,
                "evidence_kind": row.evidence_kind,
            }
        ],
        {"judge-provider": "judge-model"},
    )
    assert health["successful_assignments"] == 1
    assert health["covered_roles"] == ["competition_judge"]


def test_invalid_review_that_omits_candidate_fails_role_evidence():
    class BadJudge:
        name = "judge-provider"

        def complete(self, system, prompt):
            marker = "CANDIDATE CONCEPTS TO JUDGE:\n"
            body = prompt.split(marker, 1)[1].split("\n\nEvaluate these candidates only.", 1)[0]
            candidates = json.loads(body)
            first = candidates[0]["id"]
            return json.dumps({
                "review": {
                    "reviewed_ids": [first],
                    "winner_id": first,
                    "ranking": [{"id": first, "score": 9, "reason": "Only one candidate was reviewed."}],
                    "fatal_risks": [],
                    "summary": "Incomplete review.",
                }
            })

    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    _, _, contributions = SwarmStudio(
        [(JudgeSpec(), BadJudge())], seed=13, max_workers=1
    ).ideate(brief, deterministic_seeds=4, concepts_per_call=3)
    assert contributions[0].ok is False
    assert contributions[0].evidence_kind == "concept_review"
    assert "every supplied candidate" in contributions[0].error
