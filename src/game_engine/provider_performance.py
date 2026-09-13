from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _rows(path: Path) -> list[dict[str, Any]]:
    payload = _json(path, [])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _critic_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _rows(path):
        nested = row.get("critic_audits")
        if isinstance(nested, list):
            rows.extend(item for item in nested if isinstance(item, dict))
        elif "ok" in row and row.get("provider"):
            rows.append(row)
    return rows


def _provider_record() -> dict[str, Any]:
    return {
        "ideation": {
            "assignments": 0,
            "successes": 0,
            "failures": 0,
            "skipped": 0,
            "concepts_generated": 0,
            "roles": {},
            "failure_classes": {},
            "elapsed_seconds": [],
            "models": {},
        },
        "builder": {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "contract_repairs": 0,
            "contract_repair_survivors": 0,
            "compressed_bytes": [],
        },
        "downstream": {
            "semantic_qualified": 0,
            "semantic_blocked": 0,
            "reference_browser_qualified": 0,
            "behaviorally_qualified": 0,
            "behavioral_repair_required": 0,
            "behavioral_evidence_incomplete": 0,
            "cross_browser_qualified": 0,
        },
        "critics": {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "serialization_recoveries": 0,
            "successful_recoveries": 0,
            "model_ids": {},
        },
        "repairs": {
            "behavioral_attempts": 0,
            "behavioral_successes": 0,
            "critic_repair_attempts": 0,
            "critic_repair_successes": 0,
        },
    }


def _inc(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = int(mapping.get(key, 0)) + amount


def _build_provider_map(run_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in (
        run_root / "builds-a" / "builds.json",
        run_root / "builds-b" / "builds.json",
        run_root / "behavior-repairs-a" / "builds.json",
        run_root / "behavior-repairs-b" / "builds.json",
        run_root / "repair-cycle-a" / "repairs" / "builds.json",
        run_root / "repair-cycle-b" / "repairs" / "builds.json",
    ):
        for row in _rows(path):
            build_id = row.get("build_id")
            provider = row.get("provider")
            if build_id and provider and str(build_id) != "failed":
                mapping[str(build_id)] = str(provider)
    return mapping


def _record_staged_evidence(
    providers: defaultdict[str, dict[str, Any]],
    build_provider: dict[str, str],
    path: Path,
) -> None:
    payload = _json(path, None)
    if not isinstance(payload, dict):
        return
    fields = {
        "semantic_qualified_build_ids": "semantic_qualified",
        "semantic_blocked_build_ids": "semantic_blocked",
        "reference_browser_build_ids": "reference_browser_qualified",
        "behaviorally_qualified_build_ids": "behaviorally_qualified",
        "behavioral_repair_build_ids": "behavioral_repair_required",
        "insufficient_evidence_build_ids": "behavioral_evidence_incomplete",
        "cross_browser_build_ids": "cross_browser_qualified",
    }
    for source_field, counter in fields.items():
        for raw_build_id in payload.get(source_field, []) or []:
            provider = build_provider.get(str(raw_build_id))
            if provider:
                providers[provider]["downstream"][counter] += 1


def compile_provider_performance(run_root: Path, output_path: Path | None = None) -> dict:
    """Summarize provider outcomes by phase without granting routing authority."""
    providers: defaultdict[str, dict[str, Any]] = defaultdict(_provider_record)

    for path in (
        run_root / "swarm-primary" / "contributions.json",
        run_root / "swarm-rescue" / "contributions.json",
    ):
        for row in _rows(path):
            provider = str(row.get("provider") or "unknown")
            phase = providers[provider]["ideation"]
            phase["assignments"] += 1
            role = str(row.get("role") or "unknown")
            roles = phase["roles"]
            roles.setdefault(role, {"assignments": 0, "successes": 0, "failures": 0, "skipped": 0})
            roles[role]["assignments"] += 1
            model = row.get("model")
            if model:
                _inc(phase["models"], str(model))
            if row.get("elapsed_seconds") is not None and not row.get("skipped"):
                phase["elapsed_seconds"].append(float(row["elapsed_seconds"]))
            if row.get("ok"):
                phase["successes"] += 1
                roles[role]["successes"] += 1
                phase["concepts_generated"] += len(row.get("concept_ids") or [])
            elif row.get("skipped"):
                phase["skipped"] += 1
                roles[role]["skipped"] += 1
            else:
                phase["failures"] += 1
                roles[role]["failures"] += 1
            failure_class = row.get("failure_class")
            if failure_class:
                _inc(phase["failure_classes"], str(failure_class))

    for path in (
        run_root / "builds-a" / "builds.json",
        run_root / "builds-b" / "builds.json",
    ):
        for row in _rows(path):
            provider = str(row.get("provider") or "unknown")
            phase = providers[provider]["builder"]
            phase["attempts"] += 1
            if row.get("ok"):
                phase["successes"] += 1
                if row.get("compressed_bytes") is not None:
                    phase["compressed_bytes"].append(int(row["compressed_bytes"]))
            else:
                phase["failures"] += 1
            if row.get("contract_repair_attempted"):
                phase["contract_repairs"] += 1
                if row.get("ok") and not (row.get("contract_repair_remaining_blockers") or []):
                    phase["contract_repair_survivors"] += 1

    build_provider = _build_provider_map(run_root)
    for path in (
        run_root / "staged-a" / "staged-evidence.json",
        run_root / "staged-b" / "staged-evidence.json",
        run_root / "staged-repair-a" / "staged-evidence.json",
        run_root / "staged-repair-b" / "staged-evidence.json",
        run_root / "repair-cycle-a" / "staged-evidence" / "staged-evidence.json",
        run_root / "repair-cycle-b" / "staged-evidence" / "staged-evidence.json",
    ):
        _record_staged_evidence(providers, build_provider, path)

    for path in (
        run_root / "audit-a" / "audits.json",
        run_root / "audit-b" / "audits.json",
        run_root / "repair-cycle-a" / "audit" / "audits.json",
        run_root / "repair-cycle-b" / "audit" / "audits.json",
    ):
        for row in _critic_rows(path):
            provider = str(row.get("provider") or "unknown")
            phase = providers[provider]["critics"]
            phase["calls"] += 1
            if row.get("ok"):
                phase["successes"] += 1
            else:
                phase["failures"] += 1
            model_id = row.get("model_id")
            if model_id:
                _inc(phase["model_ids"], str(model_id))
            if row.get("recovery_attempted"):
                phase["serialization_recoveries"] += 1
                if row.get("ok"):
                    phase["successful_recoveries"] += 1

    for path, attempt_key, success_key in (
        (run_root / "behavior-repairs-a" / "builds.json", "behavioral_attempts", "behavioral_successes"),
        (run_root / "behavior-repairs-b" / "builds.json", "behavioral_attempts", "behavioral_successes"),
        (run_root / "repair-cycle-a" / "repairs" / "builds.json", "critic_repair_attempts", "critic_repair_successes"),
        (run_root / "repair-cycle-b" / "repairs" / "builds.json", "critic_repair_attempts", "critic_repair_successes"),
    ):
        for row in _rows(path):
            provider = str(row.get("provider") or "unknown")
            providers[provider]["repairs"][attempt_key] += 1
            if row.get("ok"):
                providers[provider]["repairs"][success_key] += 1

    normalized: dict[str, Any] = {}
    for provider, record in sorted(providers.items()):
        ideation = record["ideation"]
        elapsed = ideation.pop("elapsed_seconds")
        ideation["latency_observations"] = len(elapsed)
        ideation["observed_call_seconds"] = round(sum(elapsed), 6)
        ideation["mean_call_seconds"] = round(sum(elapsed) / len(elapsed), 6) if elapsed else None
        ideation["max_call_seconds"] = round(max(elapsed), 6) if elapsed else None

        builder = record["builder"]
        byte_rows = builder.pop("compressed_bytes")
        builder["compressed_bytes_observations"] = byte_rows
        builder["mean_compressed_bytes"] = (
            round(sum(byte_rows) / len(byte_rows), 1) if byte_rows else None
        )
        normalized[provider] = record

    payload = {
        "schema_version": "0.2",
        "mode": "shadow",
        "run_root": str(run_root),
        "routing_authority": False,
        "providers": normalized,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
