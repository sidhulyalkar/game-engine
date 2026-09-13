from __future__ import annotations

import json

from .agents import AgentRole
from .schema import Brief, Concept


SYSTEM = """You are one specialist inside an adversarial game-design swarm. Your job is not to be agreeable. Protect your assigned mission, produce concrete mechanics, and optimize player-visible value under severe byte constraints. Avoid generic genre reskins. Return JSON only when requested. Brevity is part of correctness: do not turn compact game concepts into design documents."""

REVIEW_SYSTEM = """You are an independent competition judge inside an adversarial game-design swarm. Evaluate the supplied candidate concepts exactly as written. Do not invent, rewrite, expand, or substitute a concept. Rank the candidates against the brief and your judging mission. Return only the requested JSON object, with no markdown or hidden reasoning."""


def _seed_payload(seeds: list[Concept]) -> list[dict]:
    return [
        {
            "id": c.concept_id,
            "title": c.title,
            "hook": c.hook,
            "core_mechanic": c.core_mechanic,
            "player_goal": c.player_goal,
            "controls": c.controls,
            "core_loop": c.core_loop,
            "escalation": c.escalation,
            "visual_grammar": c.visual_grammar,
            "audio_grammar": c.audio_grammar,
            "category_fit": c.category_fit,
            "byte_hypothesis": c.byte_hypothesis,
            "risks": c.risks,
            "tags": c.tags,
        }
        for c in seeds
    ]


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
            "title": "short string",
            "hook": "one sentence, target <=25 words",
            "core_mechanic": "one mechanically precise paragraph, target <=60 words; hard validator limit is 90",
            "player_goal": "one short sentence",
            "controls": "compact player-facing controls, target <=30 words",
            "core_loop": ["step 1", "step 2", "step 3"],
            "escalation": ["rule change", "combination", "mastery test"],
            "visual_grammar": "one compact sentence",
            "audio_grammar": "one compact sentence",
            "category_fit": [brief.primary_category or "desktop"],
            "byte_hypothesis": "one compact implementation sentence",
            "risks": ["specific risk"],
            "tags": ["mechanic", "physics", "structure"]
        }]
    }
    return f"""ROLE: {role.name}\nMISSION: {role.mission}\nVETO: {role.veto or 'none'}\n\nBRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nPRIMARY MEDIUM FOR THIS CORE SEARCH: {brief.primary_category or 'desktop'}\nEXPANSION LANES, NOT CURRENT REQUIREMENTS: {json.dumps(brief.expansion_categories)}\nNATIVE HYBRID: {brief.native_hybrid}\n\nMECHANIC SEEDS (reinterpret, do not merely rename):\n{json.dumps(seed_payload, indent=2)}\n\nGenerate exactly {count} substantially different concepts. Theme should alter play/state when possible. Favor one deep interaction over feature lists. The core mechanic must be a playable game by itself, not a bundle of modes or meta systems.\n\nHARD RESPONSE DISCIPLINE:\n- hook: target <=25 words, validator rejects >60\n- core_mechanic: target <=60 words, validator rejects >90\n- controls: target <=30 words, validator rejects >60\n- core_loop: 2-5 short steps\n- escalation: 1-4 short rules/beats\n- risks: at most 3 concrete risks\n- do not put backstory, rationale, optional modes, progression trees, networking plans, or implementation commentary inside core_mechanic\n- before returning JSON, silently check every concept against these limits; a rejected concept contributes zero value\n\nControls must be learnable quickly. Every graphical/audio flourish must have a procedural implementation story.\n\nUnless NATIVE HYBRID is true, design ONLY for the PRIMARY MEDIUM in this round. Do not add networking, touch-specific systems, WebXR embodiment, cross-device play, leaderboards, daily seeds, persistence, or other expansion-lane machinery merely because the project may explore those later. If a partner/ghost is mechanically essential in a non-online core, it must work as a deterministic local echo/AI with no network dependency.\n\nReturn exactly this JSON shape and no markdown:\n{json.dumps(schema, indent=2)}"""


def reviewer_prompt(role: AgentRole, brief: Brief, seeds: list[Concept]) -> str:
    seed_payload = _seed_payload(seeds)
    ids = [row["id"] for row in seed_payload]
    schema = {
        "review": {
            "reviewed_ids": ids,
            "winner_id": ids[0] if ids else "candidate-id",
            "ranking": [
                {
                    "id": candidate_id,
                    "score": 0.0,
                    "reason": "one concise evidence-based sentence",
                }
                for candidate_id in ids
            ],
            "fatal_risks": ["specific risk if any"],
            "summary": "one concise comparative judgment",
        }
    }
    return f"""ROLE: {role.name}\nMISSION: {role.mission}\nVETO: {role.veto or 'none'}\n\nBRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nCANDIDATE CONCEPTS TO JUDGE:\n{json.dumps(seed_payload, indent=2)}\n\nEvaluate these candidates only. Do NOT generate a replacement concept. Judge innovation, theme-as-state, first-minute gameplay, mastery potential, visual/audio communication, control clarity, procedural/13KB feasibility, category fit, and memorability.\n\nHARD RESPONSE DISCIPLINE:\n- reviewed_ids must contain every supplied candidate id exactly once\n- ranking must contain every supplied candidate id exactly once, best first\n- score is numeric 0..10 and is comparative evidence, not a promise of fun\n- winner_id must be the first ranking id\n- each reason <=25 words\n- fatal_risks contains at most 3 concrete risks\n- summary <=80 words\n- do not invent, rewrite, or add mechanics\n\nReturn exactly this JSON shape and no markdown:\n{json.dumps(schema, indent=2)}"""
