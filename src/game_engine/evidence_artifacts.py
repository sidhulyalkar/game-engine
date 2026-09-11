from __future__ import annotations

import json
from pathlib import Path

from .evidence_contract import (
    EvidenceLedger,
    claims_from_staged_evidence,
    claims_from_template_report,
    regression_claim,
    replay_claim,
    write_ledger,
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

    index = {
        "schema_version": "0.1",
        "lineage": lineage,
        "subjects": sorted(rows),
        "ledgers": {build_id: f"{build_id}.json" for build_id in sorted(rows)},
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return rows


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
