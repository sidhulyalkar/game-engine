from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .evidence_contract import (
    EvidenceClaim,
    EvidenceLedger,
    claims_from_staged_evidence,
    claims_from_template_report,
    critic_quorum_claim,
    critic_resolution_claim,
    regression_claim,
    replay_claim,
    write_ledger,
)
from .evidence_scheduler import next_generated_action


def _ledger_from_payload(payload: dict) -> EvidenceLedger:
    claims = [EvidenceClaim(**row) for row in payload.get("claims", [])]
    return EvidenceLedger(
        subject_id=str(payload["subject_id"]),
        lineage=str(payload["lineage"]),
        claims=claims,
    )


def compile_staged_ledgers(
    staged_evidence_path: Path,
    output_dir: Path,
    *,
    lineage: str = "generated-web",
) -> dict[str, dict]:
    payload = json.loads(staged_evidence_path.read_text())
    ids: set[str] = set()
    for key in (
        "semantic_qualified_build_ids",
        "semantic_blocked_build_ids",
        "reference_browser_build_ids",
        "behaviorally_qualified_build_ids",
        "behavioral_repair_build_ids",
        "insufficient_evidence_build_ids",
        "cross_browser_build_ids",
    ):
        ids.update(str(value) for value in payload.get(key, []))
    if not ids:
        raise ValueError("staged evidence contains no build identities")

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict] = {}
    decisions: dict[str, dict] = {}
    for build_id in sorted(ids):
        ledger = EvidenceLedger(
            subject_id=build_id,
            lineage=lineage,
            claims=claims_from_staged_evidence(
                payload,
                build_id,
                artifact=str(staged_evidence_path),
            ),
        )
        rows[build_id] = write_ledger(output_dir / f"{build_id}.json", ledger)
        decisions[build_id] = asdict(next_generated_action(ledger))

    index = {
        "schema_version": "0.1",
        "lineage": lineage,
        "subjects": sorted(rows),
        "ledgers": {build_id: f"{build_id}.json" for build_id in sorted(rows)},
        "shadow_scheduler_decisions": decisions,
        "scheduler_mode": "shadow",
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return rows


def enrich_generated_ledger_with_critic_audit(
    ledger_path: Path,
    audit_summary_path: Path,
    output_path: Path,
) -> dict:
    """Attach critic quorum and verdict without mutating objective evidence.

    Audit summary rows are build-scoped. A build-id mismatch fails closed instead of
    borrowing a sibling's critic verdict. Existing critic claims are replaced rather
    than duplicated so replaying the same enrichment is deterministic.
    """
    ledger = _ledger_from_payload(json.loads(ledger_path.read_text()))
    if ledger.lineage not in {"generated-web", "generated", "behavioral-repair", "critic-repair"}:
        raise ValueError(f"critic enrichment does not own lineage {ledger.lineage!r}")

    audit = json.loads(audit_summary_path.read_text())
    ranking = [row for row in audit.get("ranking", []) if isinstance(row, dict)]
    matches = [row for row in ranking if str(row.get("build_id")) == ledger.subject_id]
    if not matches:
        raise ValueError(f"audit summary has no row for build {ledger.subject_id}")
    if len(matches) != 1:
        raise ValueError(f"audit summary has duplicate rows for build {ledger.subject_id}")
    row = matches[0]
    count = int(row.get("critic_count", 0))
    status = str(row.get("status") or "")

    preserved = [
        claim for claim in ledger.claims
        if claim.scope not in {"critic_quorum", "critic_resolution"}
    ]
    artifact = str(audit_summary_path)
    preserved.extend([
        critic_quorum_claim(count, artifact=artifact),
        critic_resolution_claim(status, count, artifact=artifact),
    ])
    enriched = EvidenceLedger(
        subject_id=ledger.subject_id,
        lineage=ledger.lineage,
        claims=preserved,
    )
    payload = write_ledger(output_path, enriched)
    payload["shadow_scheduler_decision"] = asdict(next_generated_action(enriched))
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def compile_scheduler_decision(
    ledger_path: Path,
    output_path: Path | None = None,
) -> dict:
    """Compile one inspectable next-action decision without executing it."""
    ledger = _ledger_from_payload(json.loads(ledger_path.read_text()))
    if ledger.lineage not in {"generated-web", "generated", "behavioral-repair", "critic-repair"}:
        raise ValueError(f"generated scheduler does not own lineage {ledger.lineage!r}")
    payload = {
        "schema_version": "0.1",
        "mode": "shadow",
        "subject_id": ledger.subject_id,
        "lineage": ledger.lineage,
        "decision": asdict(next_generated_action(ledger)),
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def compile_template_ledger(
    report_path: Path,
    output_path: Path,
    *,
    replay_report_path: Path | None = None,
    regressions_passed: bool | None = None,
) -> dict:
    report = json.loads(report_path.read_text())
    source = report.get("source") or {}
    source_sha = str(source.get("sha256") or "unknown-source")
    scenario_sha = str(report.get("scenario_sha256") or "unknown-scenario")
    template = str((report.get("scenario") or {}).get("template") or "template")
    subject_id = f"{template}:{source_sha[:16]}:{scenario_sha[:16]}"

    claims = claims_from_template_report(report, artifact=str(report_path))
    if replay_report_path is not None:
        replay = json.loads(replay_report_path.read_text())
        claims.append(
            replay_claim(
                replay.get("replay_matches") if "replay_matches" in replay else None,
                artifact=str(replay_report_path),
            )
        )
    if regressions_passed is not None:
        claims.append(regression_claim(regressions_passed))

    return write_ledger(
        output_path,
        EvidenceLedger(subject_id=subject_id, lineage="trusted-template", claims=claims),
    )
