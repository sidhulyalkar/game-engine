from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


EVIDENCE_SCOPES = (
    "source_semantics",
    "reference_browser",
    "causal_controls",
    "restart_integrity",
    "independent_pixels",
    "cross_browser",
    "instrumented_simulation",
    "exact_replay",
    "template_regressions",
    "critic_quorum",
    "critic_resolution",
    "human_fun",
)

_STATES = {"qualified", "repair_required", "failed", "incomplete", "not_evaluated"}


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    scope: str
    state: str
    source: str
    artifact: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in EVIDENCE_SCOPES:
            raise ValueError(f"unknown evidence scope: {self.scope}")
        if self.state not in _STATES:
            raise ValueError(f"unknown evidence state: {self.state}")
        if not self.source.strip():
            raise ValueError("evidence source cannot be empty")


@dataclass(slots=True)
class EvidenceLedger:
    subject_id: str
    lineage: str
    claims: list[EvidenceClaim]

    def state(self, scope: str) -> str:
        if scope not in EVIDENCE_SCOPES:
            raise ValueError(f"unknown evidence scope: {scope}")
        rows = [claim for claim in self.claims if claim.scope == scope]
        if not rows:
            return "not_evaluated"
        # Explicit rejection dominates repair; repair dominates evidence gaps. This
        # prevents a later weak/partial observation from silently promoting a lineage
        # that already has a stronger negative decision attached to it.
        if any(row.state == "failed" for row in rows):
            return "failed"
        if any(row.state == "repair_required" for row in rows):
            return "repair_required"
        if any(row.state == "incomplete" for row in rows):
            return "incomplete"
        if any(row.state == "qualified" for row in rows):
            return "qualified"
        return "not_evaluated"

    def qualified(self, scopes: Iterable[str]) -> bool:
        return all(self.state(scope) == "qualified" for scope in scopes)

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.2",
            "subject_id": self.subject_id,
            "lineage": self.lineage,
            "claims": [asdict(claim) for claim in self.claims],
            "scope_states": {scope: self.state(scope) for scope in EVIDENCE_SCOPES},
        }


def claims_from_staged_evidence(payload: dict, build_id: str, artifact: str | None = None) -> list[EvidenceClaim]:
    """Translate generated-web-game evidence without granting unmeasured capabilities.

    Historical staged-funnel failures retain their v0.10 `failed` representation for
    artifact compatibility. The new `repair_required` state is introduced first at
    critic resolution, where quorum, repair, and rejection were previously conflated.
    """
    build_id = str(build_id)
    source = "staged_web_evidence"
    claims: list[EvidenceClaim] = []

    semantic = {str(value) for value in payload.get("semantic_qualified_build_ids", [])}
    blocked = {str(value) for value in payload.get("semantic_blocked_build_ids", [])}
    reference = {str(value) for value in payload.get("reference_browser_build_ids", [])}
    behavioral = {str(value) for value in payload.get("behaviorally_qualified_build_ids", [])}
    repair = {str(value) for value in payload.get("behavioral_repair_build_ids", [])}
    insufficient = {str(value) for value in payload.get("insufficient_evidence_build_ids", [])}
    cross = {str(value) for value in payload.get("cross_browser_build_ids", [])}

    if build_id in semantic:
        claims.append(EvidenceClaim("source_semantics", "qualified", source, artifact))
    elif build_id in blocked:
        claims.append(EvidenceClaim("source_semantics", "failed", source, artifact))

    if build_id in reference:
        claims.append(EvidenceClaim("reference_browser", "qualified", source, artifact))

    if build_id in behavioral:
        for scope in ("causal_controls", "restart_integrity", "independent_pixels"):
            claims.append(EvidenceClaim(scope, "qualified", source, artifact))
    elif build_id in repair:
        for scope in ("causal_controls", "restart_integrity", "independent_pixels"):
            claims.append(EvidenceClaim(scope, "failed", source, artifact, "behavioral repair required"))
    elif build_id in insufficient:
        for scope in ("causal_controls", "restart_integrity", "independent_pixels"):
            claims.append(EvidenceClaim(scope, "incomplete", source, artifact))

    if build_id in cross:
        claims.append(EvidenceClaim("cross_browser", "qualified", source, artifact))
    elif payload.get("promotion_attempted") and build_id in behavioral:
        claims.append(EvidenceClaim("cross_browser", "failed", source, artifact))

    return claims


def claims_from_template_report(report: dict, *, artifact: str | None = None) -> list[EvidenceClaim]:
    """Translate trusted-template scenario evidence without claiming rendering or fun."""
    status = str(report.get("status", ""))
    if status == "passed_checks":
        state = "qualified"
    elif status == "failed":
        state = "failed"
    else:
        state = "incomplete"
    return [
        EvidenceClaim(
            "instrumented_simulation",
            state,
            "template_playtest",
            artifact,
            str(report.get("scope") or "instrumented scenario evidence"),
        )
    ]


def replay_claim(replay_matches: bool | None, *, artifact: str | None = None) -> EvidenceClaim:
    state = "qualified" if replay_matches is True else "failed" if replay_matches is False else "incomplete"
    return EvidenceClaim("exact_replay", state, "template_replay", artifact)


def regression_claim(passed: bool | None, *, artifact: str | None = None) -> EvidenceClaim:
    state = "qualified" if passed is True else "failed" if passed is False else "incomplete"
    return EvidenceClaim("template_regressions", state, "template_regression_suite", artifact)


def critic_quorum_claim(critic_count: int, *, artifact: str | None = None) -> EvidenceClaim:
    state = "qualified" if int(critic_count) >= 2 else "incomplete"
    return EvidenceClaim("critic_quorum", state, "independent_llm_critics", artifact, f"critic_count={int(critic_count)}")


def critic_resolution_claim(
    status: str | None,
    critic_count: int,
    *,
    artifact: str | None = None,
) -> EvidenceClaim:
    """Encode what a complete critic quorum decided, separately from quorum itself."""
    count = int(critic_count)
    verdict = str(status or "").strip().lower()
    if count < 2:
        state = "incomplete"
        detail = f"critic_count={count}; verdict={verdict or 'unknown'}"
    elif verdict == "advance":
        state = "qualified"
        detail = "independent critic quorum recommends advance"
    elif verdict == "repair":
        state = "repair_required"
        detail = "independent critic quorum requires bounded repair"
    elif verdict == "reject":
        state = "failed"
        detail = "independent critic quorum rejects candidate"
    else:
        state = "incomplete"
        detail = f"critic_count={count}; unrecognized verdict={verdict or 'unknown'}"
    return EvidenceClaim("critic_resolution", state, "independent_llm_critics", artifact, detail)


def write_ledger(path: Path, ledger: EvidenceLedger) -> dict:
    payload = ledger.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
