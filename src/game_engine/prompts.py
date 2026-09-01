from __future__ import annotations

import json

from .agents import AgentRole
from .schema import Brief, Concept


SYSTEM = """You are one specialist inside an adversarial game-design swarm. Your job is not to be agreeable. Protect your assigned mission, produce concrete mechanics, and optimize player-visible value under severe byte constraints. Avoid generic genre reskins. Return JSON only when requested."""


def inventor_prompt(role: AgentRole, brief: Brief, seeds: list[Concept], count: int = 3) -> str:
    seed_payload = [
        {
            "id": c.concept_id,
            "hook": c.hook,
            "core_mechanic": c.core_mechanic,
            "tags": c.tags,
        }
        for c in seeds
    ]
    schema = {
        "concepts": [{
            "title": "string",
            "hook": "one sentence, ideally <=30 words",
            "core_mechanic": "one mechanically precise paragraph, <=90 words",
            "player_goal": "string",
            "controls": "string",
            "core_loop": ["step 1", "step 2", "step 3"],
            "escalation": ["rule 1", "combination", "boss/mastery test"],
            "visual_grammar": "string",
            "audio_grammar": "string",
            "category_fit": ["desktop"],
            "byte_hypothesis": "how this plausibly fits",
            "risks": ["risk"],
            "tags": ["mechanic", "physics", "structure"]
        }]
    }
    return f"""ROLE: {role.name}\nMISSION: {role.mission}\nVETO: {role.veto or 'none'}\n\nBRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nMECHANIC SEEDS (reinterpret, do not merely rename):\n{json.dumps(seed_payload, indent=2)}\n\nGenerate exactly {count} substantially different concepts. Theme should alter play/state when possible. Favor one deep interaction over feature lists. The core mechanic must be a playable game by itself, not a bundle of modes or meta systems. Keep core_mechanic <=90 words; use escalation for later richness. Controls must be learnable quickly. Every graphical/audio flourish must have a procedural implementation story. Daily seeds, leaderboards, ghosts, networking, co-op, progression systems, and social features are optional wrappers, not substitutes for the core interaction; keep them outside core_mechanic unless your specialist mission absolutely requires one, and preserve a complete offline core first.\n\nReturn exactly this JSON shape and no markdown:\n{json.dumps(schema, indent=2)}"""
