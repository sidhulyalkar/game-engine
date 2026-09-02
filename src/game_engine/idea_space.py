from __future__ import annotations

import hashlib
import random
from dataclasses import replace

from .schema import Brief, Concept


VERBS = [
    "stretch", "orbit", "grind", "reflect", "split", "braid", "phase",
    "tether", "slingshot", "paint", "fold", "echo", "swap", "magnetize",
]
PHYSICS = [
    "spring tension", "angular momentum", "reflection", "elastic collision",
    "gravity inversion", "friction lanes", "wave interference", "shared inertia",
]
STRUCTURES = [
    "boss rush", "score attack", "micro-roguelite", "one-room duel", "survival ladder",
    "rhythm route", "territory tug-of-war", "delivery gauntlet", "precision traversal",
]
TWISTS = [
    "the weapon is also the movement system",
    "taking damage changes the rules instead of only lowering health",
    "the arena is drawn by the player during play",
    "every enemy becomes terrain after defeat",
    "the safest action makes the next ten seconds harder",
    "two control schemes must cooperate through one body",
    "color is state, not decoration",
    "the score multiplier is physically present and can be lost",
]
VISUALS = [
    "vector neon with additive trails", "chunky low-poly illusion on Canvas 2D",
    "procedural stained-glass shards", "elastic cartoon silhouettes",
    "CRT prism bloom made from layered alpha shapes", "ink-and-rainbow negative space",
]
AUDIO = [
    "WebAudio kick/bass pulses coupled to collisions",
    "procedural arpeggios where game state chooses notes",
    "percussion synthesized from impacts and combo state",
    "minimal bass motif that gains voices with risk",
]


def _stable_id(seed: int, index: int, title: str) -> str:
    raw = f"{seed}:{index}:{title}".encode()
    return hashlib.sha1(raw).hexdigest()[:8]


def procedural_concepts(brief: Brief, count: int = 24, seed: int = 13) -> list[Concept]:
    rng = random.Random(seed)
    concepts: list[Concept] = []
    nouns = ["Prism", "Horn", "Rainbow", "Comet", "Tether", "Herd", "Halo", "Rift"]
    for i in range(count):
        verb = rng.choice(VERBS)
        physics = rng.choice(PHYSICS)
        structure = rng.choice(STRUCTURES)
        twist = rng.choice(TWISTS)
        title = f"{rng.choice(nouns)} {rng.choice(['Riot','Rail','Relay','Rift','Circuit','Stampede','Splice','Crash'])}"
        mechanic = f"Players {verb} through {physics}; {twist}."
        cid = _stable_id(seed, i, title)
        categories = list(brief.active_categories)
        concepts.append(
            Concept(
                concept_id=cid,
                title=title,
                hook=f"A {structure} where {mechanic.lower()}",
                core_mechanic=mechanic,
                player_goal=f"Master the risk/reward rhythm of {verb} to clear escalating encounters and chase a replayable score.",
                controls="Two movement inputs plus one context action; advanced depth comes from timing and geometry, not more buttons.",
                core_loop=["read the arena", f"commit to {verb}", "convert danger into position or score", "cash out or push the multiplier"],
                escalation=["introduce one rule", "combine two known rules", "invert a learned assumption", "boss tests mastery without new controls"],
                visual_grammar=rng.choice(VISUALS),
                audio_grammar=rng.choice(AUDIO),
                category_fit=categories,
                byte_hypothesis="Canvas/WebAudio primitives, seeded content, data-driven enemies, no shipped media assets.",
                risks=["mechanic readability", "difficulty curve", "compressed tutorial budget"],
                tags=[verb, physics, structure, brief.theme.lower(), f"primary:{brief.primary_category or 'desktop'}"],
            )
        )
    return concepts


def mutate(concept: Concept, seed: int, mutation_index: int) -> Concept:
    rng = random.Random(seed * 1009 + mutation_index)
    new_verb = rng.choice([v for v in VERBS if v not in concept.tags])
    new_twist = rng.choice(TWISTS)
    return replace(
        concept,
        concept_id=_stable_id(seed, mutation_index, concept.title + new_verb),
        title=f"{concept.title} // {new_verb.title()}",
        hook=f"{concept.hook} Mutation: {new_twist}.",
        core_mechanic=f"{concept.core_mechanic} Add a tightly-coupled {new_verb} decision without adding a new button.",
        lineage=concept.lineage + [concept.concept_id],
        tags=concept.tags + [new_verb, "mutation"],
    )
