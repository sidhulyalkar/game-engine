from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .provider_observation import observation_from_usage, provider_token_counts


def _json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _rows(path: Path) -> list[dict[str, Any]]:
    payload = _json(path, [])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _critic_rows(path: Path) -> list[dict[str, Any]]:
    """Return actual critic attempts from aggregate or legacy flat audit artifacts."""
    rows: list[dict[str, Any]] = []
    for row in _rows(path):
        nested = row.get("critic_audits")
        if isinstance(nested, list):
            rows.extend(item for item in nested if isinstance(item, dict))
        elif "ok" in row and row.get("provider"):
            rows.append(row)
    return rows


def _economics_record() -> dict[str, Any]:
    return {
        "observed_calls": 0,
        "timing_observations": 0,
        "total_elapsed_ms": 0.0,
        "mean_elapsed_ms": None,
        "attempt_count_observations": 0,
        "total_attempts": 0,
        "total_retries": 0,
        "token_observations": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


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
            "skipped": 0,
            "failure_classes": {},
        },
        "observed_economics": {
            "ideation": _economics_record(),
            "builder": _economics_record(),
            "critic": _economics_record(),
            "repair": _economics_record(),
        },
    }


def _inc(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = int(mapping.get(key, 0)) + amount


def _observe_usage(economics: dict[str, Any], usage: object) -> None:
    """Accumulate only values actually emitted by a provider call artifact."""
    if not isinstance(usage, dict):
        return
    observation = observation_from_usage(usage)
    tokens = provider_token_counts(usage)
    if observation is None and tokens is None:
        return
    economics["observed_calls"] += 1
    if observation is not None:
        elapsed = observation.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            economics["timing_observations"] += 1
            economics["total_elapsed_ms"] += float(elapsed)
        attempts = observation.get("attempt_count")
        if isinstance(attempts, int) and attempts >= 1:
            economics["attempt_count_observations"] += 1
            economics["total_attempts"] += attempts
            economics["total_retries"] += max(0, attempts - 1)
    if tokens is not None:
        economics["token_observations"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = tokens.get(key)
            if isinstance(value, int):
                economics[key] += value


def _observe_exception(economics: dict[str, Any], observation: object) -> None:
    if not isinstance(observation, dict):
        return
    economics["observed_calls"] += 1
    elapsed = observation.get("elapsed_ms")
    if isinstance(elapsed, (int, float)):
        economics["timing_observations"] += 1
        economics["total_elapsed_ms"] += float(elapsed)
    attempts = observation.get("attempt_count")
    if isinstance(attempts, int) and attempts >= 1:
        economics["attempt_count_observations"] += 1
        economics["total_attempts"] += attempts
        economics["total_retries"] += max(0, attempts - 1)


def _observe_meta_usage(providers: defaultdict[str, dict[str, Any]], root: Path, phase: str) -> None:
    if not root.exists():
        return
    for path in sorted(root.glob("*.json")):
        payload = _json(path, None)
        if not isinstance(payload, dict) or not payload.get("provider"):
            continue
        provider = str(payload["provider"])
        economics = providers[provider]["observed_economics"][phase]
        for key in ("usage", "recovery_usage", "contract_repair_usage"):
            _observe_usage(economics, payload.get(key))
        _observe_exception(economics, payload.get("failure_observation"))


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
            build_id = str(raw_build_id)
            provider = build_provider.get(build_id)
            if provider:
                providers[provider]["downstream"][counter] += 1


def _finalize_economics(record: dict[str, Any]) -> None:
    for phase in record["observed_economics"].values():
        n = int(phase["timing_observations"])
        phase["total_elapsed_ms"] = round(float(phase["total_elapsed_ms"]), 3)
        phase["mean_elapsed_ms"] = (
            round(float(phase["total_elapsed_ms"]) / n, 3) if n else None
        )


def compile_provider_performance(run_root: Path, output_path: Path | None = None) -> dict:
    """Summarize observed provider outcomes and economics without routing authority.

    Economics are phase-specific and missingness is explicit. No historical pricing is
    inferred and no global provider score is produced. A fast failed call and a slow
    downstream survivor remain separate facts for later calibration.
    """
    providers: defaultdict[str, dict[str, Any]] = defaultdict(_provider_record)

    # Concept work, including targeted rescue. Newer contributions may carry usage
    # observations; older artifacts remain valid with zero economics observations.
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
            _observe_usage(providers[provider]["observed_economics"]["ideation"], row.get("usage"))
            _observe_exception(
                providers[provider]["observed_economics"]["ideation"],
                row.get("failure_observation"),
            )

    # Initial implementation races.
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
            _observe_exception(
                providers[provider]["observed_economics"]["builder"],
                row.get("failure_observation"),
            )

    # Builder meta artifacts preserve initial, truncation-recovery, and deterministic
    # contract-repair calls as independent observations.
    for root in (
        run_root / "builds-a" / "meta",
        run_root / "builds-b" / "meta",
    ):
        _observe_meta_usage(providers, root, "builder")

    build_provider = _build_provider_map(run_root)
    for path in (
        run_root / "staged-a" / "staged-evidence.json",
        run_root / "staged-b" / "staged-evidence.json",
        run_root / "staged-repair-a" / "staged-evidence.json",
        run_root / "staged-repair-b" / "staged-evidence.json",
    ):
        _record_staged_evidence(providers, build_provider, path)

    # Aggregate BuildAudit rows store the builder at top level and the actual critic
    # providers in critic_audits[]. Flatten those nested attempts before attribution.
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
            economics = providers[provider]["observed_economics"]["critic"]
            _observe_usage(economics, row.get("usage"))
            if row.get("recovery_attempted"):
                phase["serialization_recoveries"] += 1
                _observe_usage(economics, row.get("recovery_usage"))
                if row.get("ok"):
                    phase["successful_recoveries"] += 1
            _observe_exception(economics, row.get("failure_observation"))

    # Bounded behavioral repairs and critic-driven repairs. Circuit-open rows are
    # scheduled opportunities but not paid model attempts.
    for path, attempt_key, success_key in (
        (run_root / "behavior-repairs-a" / "builds.json", "behavioral_attempts", "behavioral_successes"),
        (run_root / "behavior-repairs-b" / "builds.json", "behavioral_attempts", "behavioral_successes"),
        (run_root / "repair-cycle-a" / "repairs" / "builds.json", "critic_repair_attempts", "critic_repair_successes"),
        (run_root / "repair-cycle-b" / "repairs" / "builds.json", "critic_repair_attempts", "critic_repair_successes"),
    ):
        for row in _rows(path):
            provider = str(row.get("provider") or "unknown")
            phase = providers[provider]["repairs"]
            if row.get("skipped"):
                phase["skipped"] += 1
            else:
                phase[attempt_key] += 1
            if row.get("ok"):
                phase[success_key] += 1
            failure_class = row.get("failure_class")
            if failure_class:
                _inc(phase["failure_classes"], str(failure_class))
            _observe_usage(providers[provider]["observed_economics"]["repair"], row.get("usage"))
            _observe_exception(
                providers[provider]["observed_economics"]["repair"],
                row.get("failure_observation"),
            )

    # Behavioral/critic repair meta artifacts retain provider usage even if HTML or
    # deterministic source parsing rejects the child after the HTTP response.
    for root in (
        run_root / "behavior-repairs-a" / "meta",
        run_root / "behavior-repairs-b" / "meta",
        run_root / "repair-cycle-a" / "repairs" / "meta",
        run_root / "repair-cycle-b" / "repairs" / "meta",
    ):
        _observe_meta_usage(providers, root, "repair")

    normalized: dict[str, Any] = {}
    for provider, record in sorted(providers.items()):
        builder = record["builder"]
        byte_rows = builder.pop("compressed_bytes")
        builder["compressed_bytes_observations"] = byte_rows
        builder["mean_compressed_bytes"] = (
            round(sum(byte_rows) / len(byte_rows), 1) if byte_rows else None
        )
        _finalize_economics(record)
        normalized[provider] = record

    payload = {
        "schema_version": "0.3",
        "mode": "shadow",
        "run_root": str(run_root),
        "routing_authority": False,
        "economics_authority": False,
        "economics_note": (
            "Only directly observed elapsed time, retries, and provider-reported tokens are included; "
            "missing observations are never imputed and no pricing or global provider score is inferred."
        ),
        "providers": normalized,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
