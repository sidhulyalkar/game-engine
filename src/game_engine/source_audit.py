from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .providers.base import LLMClient
from .reality import discover_builds
from .schema import Brief, Concept
from .swarm import _extract_json


DIMENSIONS = (
    "concept_fidelity",
    "logic_correctness",
    "first_10s_clarity",
    "game_feel",
    "mastery_curve",
    "pacing_progression",
    "visual_identity",
    "audio_feedback",
    "replayability",
    "exploit_resistance",
)


@dataclass(slots=True)
class AuditFinding:
    severity: str
    category: str
    evidence: str
    player_impact: str
    smallest_fix: str


@dataclass(slots=True)
class CriticAudit:
    provider: str
    build_id: str
    ok: bool
    scores: dict[str, float] = field(default_factory=dict)
    verdict: str | None = None
    summary: str | None = None
    findings: list[AuditFinding] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class BuildAudit:
    build_id: str
    provider: str
    critic_count: int
    scores: dict[str, float]
    overall: float
    blockers: int
    majors: int
    verdict_votes: dict[str, int]
    status: str
    critic_audits: list[CriticAudit]


def auditor_prompt(brief: Brief, concept: Concept, build: dict, html: str, reality: list[dict]) -> tuple[str, str]:
    system = """You are a hostile senior game designer and gameplay engineer auditing a generated web game. Judge the game that the source actually implements, not the game the author intended. Find semantic bugs, concept drift, fake difficulty, dead mechanics, unreadable controls, bad pacing, unbounded state, and interactions that will feel wrong even if the page renders. Return strict JSON only."""
    schema = {
        "scores": {name: "0-10 number" for name in DIMENSIONS},
        "verdict": "advance | repair | reject",
        "summary": "one concise paragraph",
        "findings": [
            {
                "severity": "blocker | major | minor",
                "category": "logic | controls | concept | pacing | graphics | audio | exploit | performance",
                "evidence": "specific source/state evidence, <=160 chars",
                "player_impact": "what the player experiences",
                "smallest_fix": "smallest coherent fix",
            }
        ],
    }
    source = html if len(html) <= 80_000 else html[:80_000] + "\n<!-- SOURCE TRUNCATED FOR AUDIT -->"
    user = f"""COMPETITION BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nWINNING CONCEPT CONTRACT:\n{json.dumps(concept.to_dict(), indent=2)}\n\nBUILD METADATA:\n{json.dumps({k: v for k, v in build.items() if k != 'resolved_source_dir'}, indent=2)}\n\nBROWSER REALITY EVIDENCE:\n{json.dumps(reality, indent=2)}\n\nIMPLEMENTED INDEX.HTML:\n{source}\n\nAudit this implementation. Important rules:\n- A page rendering without exceptions is not proof of gameplay correctness.\n- Compare numeric units, delta-time use, object/property comparisons, cleanup conditions, collisions, scoring, restart, and state bounds carefully.\n- Compare the actual controls and movement geometry against the winning concept sentence by sentence.\n- Treat cosmetic theme substitution for a promised mechanic as concept drift.\n- Treat no meaningful escalation/mastery loop as a gameplay defect even if score increases.\n- Do not reward small byte size by itself.\n- Cite specific evidence for every blocker/major finding.\n\nReturn exactly this JSON shape with no markdown fences:\n{json.dumps(schema, indent=2)}"""
    return system, user


def _score(value) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _parse_audit(text: str, provider: str, build_id: str) -> CriticAudit:
    payload = _extract_json(text)
    if not isinstance(payload, dict):
        raise ValueError("audit payload must be an object")
    raw_scores = payload.get("scores") or {}
    scores = {name: _score(raw_scores.get(name)) for name in DIMENSIONS}
    verdict = str(payload.get("verdict", "repair")).lower().strip()
    if verdict not in {"advance", "repair", "reject"}:
        verdict = "repair"
    findings = []
    for raw in payload.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "minor")).lower()
        if severity not in {"blocker", "major", "minor"}:
            severity = "minor"
        findings.append(AuditFinding(
            severity=severity,
            category=str(raw.get("category", "logic")),
            evidence=str(raw.get("evidence", ""))[:500],
            player_impact=str(raw.get("player_impact", ""))[:500],
            smallest_fix=str(raw.get("smallest_fix", ""))[:500],
        ))
    return CriticAudit(
        provider=provider,
        build_id=build_id,
        ok=True,
        scores=scores,
        verdict=verdict,
        summary=str(payload.get("summary", ""))[:2000],
        findings=findings,
    )


def aggregate_audits(build: dict, audits: list[CriticAudit]) -> BuildAudit:
    good = [audit for audit in audits if audit.ok]
    scores = {
        name: round(statistics.mean(audit.scores[name] for audit in good), 3) if good else 0.0
        for name in DIMENSIONS
    }
    weights = {name: 1.0 for name in DIMENSIONS}
    weights["logic_correctness"] = 1.5
    weights["concept_fidelity"] = 1.5
    weights["first_10s_clarity"] = 1.25
    overall = sum(scores[name] * weights[name] for name in DIMENSIONS) / sum(weights.values()) if good else 0.0
    blockers = sum(f.severity == "blocker" for audit in good for f in audit.findings)
    majors = sum(f.severity == "major" for audit in good for f in audit.findings)
    votes = {name: sum(audit.verdict == name for audit in good) for name in ("advance", "repair", "reject")}

    if not good:
        status = "reject"
    elif (
        len(good) >= 2
        and blockers == 0
        and scores["logic_correctness"] >= 7.0
        and scores["concept_fidelity"] >= 7.0
        and scores["first_10s_clarity"] >= 6.5
        and overall >= 7.0
        and votes["advance"] >= max(1, len(good) // 2)
    ):
        status = "advance"
    elif blockers <= 1 and votes["reject"] < max(2, len(good)):
        status = "repair"
    else:
        status = "reject"

    return BuildAudit(
        build_id=build["build_id"],
        provider=build.get("provider", "unknown"),
        critic_count=len(good),
        scores=scores,
        overall=round(overall, 3),
        blockers=blockers,
        majors=majors,
        verdict_votes=votes,
        status=status,
        critic_audits=audits,
    )


def _load_reality(reality_root: Path | None) -> dict[str, list[dict]]:
    if reality_root is None:
        return {}
    path = reality_root / "reality.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    by_build: dict[str, list[dict]] = {}
    for row in rows:
        by_build.setdefault(str(row.get("build_id")), []).append(row)
    return by_build


class SourceGameplayLab:
    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 4):
        self.clients = clients
        self.max_workers = max_workers

    def run(
        self,
        brief: Brief,
        concept: Concept,
        builds_root: Path,
        output_dir: Path,
        reality_root: Path | None = None,
    ) -> dict:
        builds = discover_builds(builds_root)
        if not builds:
            raise ValueError(f"no byte-qualified builds found in {builds_root}")
        output_dir.mkdir(parents=True, exist_ok=True)
        reality = _load_reality(reality_root)
        per_build: dict[str, list[CriticAudit]] = {build["build_id"]: [] for build in builds}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for build in builds:
                html = (Path(build["resolved_source_dir"]) / "index.html").read_text()
                system, prompt = auditor_prompt(brief, concept, build, html, reality.get(build["build_id"], []))
                for spec, client in self.clients:
                    provider = getattr(spec, "name", getattr(client, "name", "critic"))
                    futures[pool.submit(client.complete, system, prompt)] = (provider, build)
            for future in as_completed(futures):
                provider, build = futures[future]
                try:
                    audit = _parse_audit(future.result(), provider, build["build_id"])
                except Exception as exc:
                    audit = CriticAudit(
                        provider=provider,
                        build_id=build["build_id"],
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                per_build[build["build_id"]].append(audit)

        summaries = [aggregate_audits(build, per_build[build["build_id"]]) for build in builds]
        summaries.sort(key=lambda row: (row.status != "advance", row.status == "reject", -row.overall))
        detailed = [
            {
                **{k: v for k, v in asdict(summary).items() if k != "critic_audits"},
                "critic_audits": [asdict(audit) for audit in summary.critic_audits],
            }
            for summary in summaries
        ]
        (output_dir / "audits.json").write_text(json.dumps(detailed, indent=2) + "\n")
        result = {
            "builds_audited": len(summaries),
            "advance_build_ids": [row.build_id for row in summaries if row.status == "advance"],
            "repair_build_ids": [row.build_id for row in summaries if row.status == "repair"],
            "reject_build_ids": [row.build_id for row in summaries if row.status == "reject"],
            "ranking": [
                {
                    "build_id": row.build_id,
                    "provider": row.provider,
                    "status": row.status,
                    "overall": row.overall,
                    "blockers": row.blockers,
                    "critic_count": row.critic_count,
                }
                for row in summaries
            ],
        }
        (output_dir / "audit-summary.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
