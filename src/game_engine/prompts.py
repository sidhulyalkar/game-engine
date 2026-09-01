from __future__ import annotations

import json

from .agents import AgentRole
from .schema import Brief, Concept


SYSTEM = """You are one specialist inside an adversarial game-design swarm. Your job is not to be agreeable. Protect your assigned mission, produce concrete mechanics, and optimize player-visible value under severe byte constraints. Avoid generic genre reskins. Return JSON only when requested. Brevity is part of correctness: do not turn compact game concepts into design documents."""


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
