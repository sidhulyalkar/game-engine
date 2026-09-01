from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field

from .agents import CATEGORY_SPECIALISTS, STUDIO_ROLES, AgentRole
from .evaluators import deduplicate, judge
from .idea_space import procedural_concepts
from .prompts import SYSTEM, inventor_prompt
from .providers.base import LLMClient
from .schema import Brief, Concept, ScoreCard


@dataclass(slots=True)
class SwarmContribution:
    provider: str
    role: str
    ok: bool
    concept_ids: list[str]
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _word_count(value: object) -> int:
    return len(str(value).split())


def _concept_from_model(item: dict, provider: str, role: str, index: int) -> Concept:
    required = [
        "title", "hook", "core_mechanic", "player_goal", "controls", "core_loop",
        "escalation", "visual_grammar", "audio_grammar", "category_fit", "byte_hypothesis",
    ]
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"concept missing fields: {', '.join(missing)}")

    # Tiny games benefit from strong concepts, not design-doc sprawl. The brief asks
    # for a one-sentence mechanic; a 150-word core is usually several games hiding
    # under one title and is unlikely to survive a 13KB implementation intact.
    if _word_count(item["hook"]) > 60:
        raise ValueError("hook exceeds 60 words")
    if _word_count(item["core_mechanic"]) > 120:
        raise ValueError("core_mechanic exceeds 120 words; split the idea into a smaller game")
    if _word_count(item["controls"]) > 60:
        raise ValueError("controls exceed 60 words")
    if not isinstance(item["core_loop"], list) or not 2 <= len(item["core_loop"]) <= 7:
        raise ValueError("core_loop must contain 2-7 steps")
    if not isinstance(item["escalation"], list) or not 1 <= len(item["escalation"]) <= 7:
        raise ValueError("escalation must contain 1-7 steps")

    raw_id = f"{provider}:{role}:{index}:{item['title']}:{item['core_mechanic']}".encode()
    cid = hashlib.sha1(raw_id).hexdigest()[:8]
    return Concept(
        concept_id=cid,
        title=str(item["title"]),
        hook=str(item["hook"]),
        core_mechanic=str(item["core_mechanic"]),
        player_goal=str(item["player_goal"]),
        controls=str(item["controls"]),
        core_loop=[str(v) for v in item["core_loop"]],
        escalation=[str(v) for v in item["escalation"]],
        visual_grammar=str(item["visual_grammar"]),
        audio_grammar=str(item["audio_grammar"]),
        category_fit=[str(v).lower() for v in item["category_fit"]],
        byte_hypothesis=str(item["byte_hypothesis"]),
        risks=[str(v) for v in item.get("risks", [])],
        lineage=[],
        tags=[str(v).lower() for v in item.get("tags", [])] + [f"provider:{provider}", f"role:{role}"],
    )


def _roles_for_brief(brief: Brief) -> list[AgentRole]:
    roles = list(STUDIO_ROLES[:-1])
    for category in brief.target_categories:
        specialist = CATEGORY_SPECIALISTS.get(category.lower())
        if specialist:
            roles.append(specialist)
    return roles


def _complete_limited(semaphore: threading.Semaphore, client: LLMClient, system: str, prompt: str) -> str:
    with semaphore:
        return client.complete(system, prompt)


class SwarmStudio:
    def __init__(self, clients: list[tuple[object, LLMClient]], seed: int = 13, max_workers: int = 8):
        self.clients = clients
        self.seed = seed
        self.max_workers = max_workers

    def ideate(self, brief: Brief, deterministic_seeds: int = 16, concepts_per_call: int = 3) -> tuple[list[Concept], list[ScoreCard], list[SwarmContribution]]:
        seeds = procedural_concepts(brief, count=deterministic_seeds, seed=self.seed)
        roles = {r.name: r for r in _roles_for_brief(brief)}
        jobs: list[tuple[object, LLMClient, AgentRole, list[Concept]]] = []
        cursor = 0
        for spec, client in self.clients:
            allowed_roles = getattr(spec, "roles", []) or list(roles)
            for role_name in allowed_roles:
                role = roles.get(role_name)
                if not role:
                    continue
                sample = [seeds[(cursor + j) % len(seeds)] for j in range(min(4, len(seeds)))]
                cursor += 3
                jobs.append((spec, client, role, sample))

        provider_limits: dict[str, threading.Semaphore] = {}
        for spec, client in self.clients:
            provider_name = getattr(spec, "name", getattr(client, "name", "provider"))
            limit = max(1, int(getattr(spec, "max_concurrency", 1)))
            provider_limits[provider_name] = threading.Semaphore(limit)

        generated: list[Concept] = []
        contributions: list[SwarmContribution] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {}
            for spec, client, role, sample in jobs:
                provider_name = getattr(spec, "name", getattr(client, "name", "provider"))
                future = pool.submit(
                    _complete_limited,
                    provider_limits[provider_name],
                    client,
                    SYSTEM,
                    inventor_prompt(role, brief, sample, concepts_per_call),
                )
                future_map[future] = (spec, client, role)

            for future in as_completed(future_map):
                spec, client, role = future_map[future]
                provider_name = getattr(spec, "name", getattr(client, "name", "provider"))
                try:
                    payload = _extract_json(future.result())
                    items = payload.get("concepts", [])
                    if not isinstance(items, list):
                        raise ValueError("concepts must be a list")
                    concepts: list[Concept] = []
                    warnings: list[str] = []
                    for i, item in enumerate(items):
                        try:
                            if not isinstance(item, dict):
                                raise ValueError("concept must be an object")
                            concepts.append(_concept_from_model(item, provider_name, role.name, i))
                        except Exception as exc:
                            warnings.append(f"concept[{i}] rejected: {type(exc).__name__}: {exc}")
                    if not concepts:
                        detail = "; ".join(warnings) if warnings else "provider returned no concepts"
                        raise ValueError(detail)
                    generated.extend(concepts)
                    contributions.append(
                        SwarmContribution(provider_name, role.name, True, [c.concept_id for c in concepts], warnings=warnings)
                    )
                except Exception as exc:
                    contributions.append(
                        SwarmContribution(provider_name, role.name, False, [], f"{type(exc).__name__}: {exc}")
                    )

        population = deduplicate(seeds + generated, threshold=0.84)
        scorecards = [judge(c, brief, population) for c in population]
        scorecards.sort(key=lambda score: score.total, reverse=True)
        by_id = {c.concept_id: c for c in population}
        ranked = [by_id[s.concept_id] for s in scorecards]
        return ranked, scorecards, contributions

    def run(self, brief: Brief, output_dir, deterministic_seeds: int = 16, concepts_per_call: int = 3) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        concepts, scores, contributions = self.ideate(brief, deterministic_seeds, concepts_per_call)
        score_map = {s.concept_id: s for s in scores}
        successful = [c for c in contributions if c.ok]
        successful_providers = sorted({c.provider for c in successful})
        payload = {
            "engine_version": "0.1.0",
            "mode": "multi-model-swarm",
            "seed": self.seed,
            "brief": brief.to_dict(),
            "providers": sorted({c.provider for c in contributions}),
            "successful_providers": successful_providers,
            "successful_assignments": len(successful),
            "failed_assignments": sum(not c.ok for c in contributions),
            "partially_rejected_concepts": sum(len(c.warnings) for c in contributions),
            "population_size": len(concepts),
            "winner_id": concepts[0].concept_id if concepts else None,
        }
        (output_dir / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n")
        (output_dir / "contributions.json").write_text(json.dumps([asdict(c) for c in contributions], indent=2) + "\n")
        (output_dir / "leaderboard.json").write_text(json.dumps([
            {"rank": i + 1, "concept": c.to_dict(), "scorecard": score_map[c.concept_id].to_dict()}
            for i, c in enumerate(concepts)
        ], indent=2) + "\n")
        if concepts:
            winner = concepts[0]
            (output_dir / "winner.json").write_text(json.dumps({
                "brief": brief.to_dict(),
                "concept": winner.to_dict(),
                "scorecard": score_map[winner.concept_id].to_dict(),
                "swarm": {
                    "seed": self.seed,
                    "successful_providers": successful_providers,
                    "successful_assignments": len(successful),
                    "failed_assignments": sum(not c.ok for c in contributions),
                    "partially_rejected_concepts": sum(len(c.warnings) for c in contributions),
                },
            }, indent=2) + "\n")
        return payload
