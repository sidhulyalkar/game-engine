from __future__ import annotations

import re
from collections import Counter

from .schema import Brief, Concept, ScoreCard

CRITERIA = ("innovation", "theme", "gameplay", "graphics", "audio", "controls", "byte_fit", "replayability")


def _clamp(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 2)


def token_jaccard(a: Concept, b: Concept) -> float:
    ta = set(re.findall(r"[a-z]+", (a.hook + " " + a.core_mechanic).lower()))
    tb = set(re.findall(r"[a-z]+", (b.hook + " " + b.core_mechanic).lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def novelty_score(concept: Concept, population: list[Concept]) -> float:
    others = [token_jaccard(concept, other) for other in population if other.concept_id != concept.concept_id]
    return 10.0 if not others else _clamp(10 * (1 - max(others)))


def judge(concept: Concept, brief: Brief, population: list[Concept]) -> ScoreCard:
    text = " ".join([
        concept.hook, concept.core_mechanic, concept.controls,
        *concept.core_loop, *concept.escalation, concept.visual_grammar, concept.audio_grammar,
    ]).lower()
    controls_words = len(concept.controls.split())
    novelty = novelty_score(concept, population)
    theme_terms = set(re.findall(r"[a-z]+", brief.theme.lower()))
    theme_hits = sum(1 for t in theme_terms if t in text)
    physical_terms = sum(term in text for term in ["tension", "momentum", "collision", "timing", "geometry", "risk", "position"])
    generated_terms = sum(term in text for term in ["procedural", "canvas", "webaudio", "seeded", "primitive"])

    scores = {
        "innovation": _clamp(4.8 + novelty * 0.45 + min(1.5, physical_terms * 0.25)),
        "theme": _clamp(5.0 + min(4.0, theme_hits * 1.5) + (1.0 if "color" in text or "rainbow" in text else 0)),
        "gameplay": _clamp(5.2 + min(2.0, len(concept.core_loop) * 0.4) + min(1.8, physical_terms * 0.3)),
        "graphics": _clamp(5.3 + (1.5 if any(k in text for k in ["trail", "bloom", "glass", "alpha", "silhouette"]) else .5)),
        "audio": _clamp(5.0 + (2.0 if "webaudio" in text or "procedural" in concept.audio_grammar.lower() else .8)),
        "controls": _clamp(9.0 - max(0, controls_words - 24) * .08),
        "byte_fit": _clamp(6.5 + min(2.5, generated_terms * .55) - max(0, len(concept.escalation) - 5) * .4),
        "replayability": _clamp(5.4 + (1.4 if "score" in text or "multiplier" in text else 0) + (1.0 if "risk" in text else 0)),
    }
    weights = {"innovation": 1.25, "theme": 0.9, "gameplay": 1.45, "graphics": 1.0, "audio": 0.65, "controls": 1.05, "byte_fit": 1.35, "replayability": 1.0}
    total = round(sum(scores[k] * weights[k] for k in CRITERIA) / sum(weights.values()), 3)

    strengths = []
    weaknesses = []
    mutations = []
    for key, value in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]:
        strengths.append(f"{key}: {value}/10")
    for key, value in sorted(scores.items(), key=lambda kv: kv[1])[:3]:
        weaknesses.append(f"{key}: {value}/10")
        mutations.append(f"Raise {key} without adding control complexity or shipped assets.")

    vetoes: list[str] = []
    if scores["controls"] < 5:
        vetoes.append("control-overload")
    if scores["byte_fit"] < 5:
        vetoes.append("byte-risk")
    if scores["gameplay"] < 5:
        vetoes.append("weak-core-loop")

    return ScoreCard(concept.concept_id, scores, total, strengths, weaknesses, mutations, vetoes)


def deduplicate(concepts: list[Concept], threshold: float = 0.82) -> list[Concept]:
    kept: list[Concept] = []
    for candidate in concepts:
        if all(token_jaccard(candidate, existing) < threshold for existing in kept):
            kept.append(candidate)
    return kept


def mechanic_distribution(concepts: list[Concept]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for concept in concepts:
        counter.update(concept.tags)
    return dict(counter.most_common())
