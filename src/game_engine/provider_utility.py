from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"provider utility input must be a JSON list: {path}")
    return [row for row in payload if isinstance(row, dict)]


def _summary(rows: list[dict]) -> dict:
    attempts = [row for row in rows if not bool(row.get("skipped"))]
    successes = [row for row in attempts if bool(row.get("ok"))]
    failures = [row for row in attempts if not bool(row.get("ok"))]
    skipped = [row for row in rows if bool(row.get("skipped"))]
    operational = [
        row for row in failures
        if row.get("failure_class") in {
            "transport",
            "server_5xx",
            "rate_limit",
            "endpoint_or_model_not_found",
        }
    ]
    content_or_schema = [row for row in failures if not row.get("failure_class")]
    latencies = [
        float(row["elapsed_seconds"])
        for row in attempts
        if row.get("elapsed_seconds") is not None
    ]
    accepted_concepts = sum(len(row.get("concept_ids") or []) for row in successes)
    rejected_concepts = sum(len(row.get("warnings") or []) for row in rows)
    attempt_count = len(attempts)
    success_count = len(successes)
    return {
        "scheduled_assignments": len(rows),
        "attempted_assignments": attempt_count,
        "successful_assignments": success_count,
        "failed_assignments": len(failures),
        "skipped_assignments": len(skipped),
        "operational_failures": len(operational),
        "content_or_schema_failures": len(content_or_schema),
        "accepted_concepts": accepted_concepts,
        "partially_rejected_concepts": rejected_concepts,
        "success_rate": round(success_count / attempt_count, 6) if attempt_count else None,
        "smoothed_reliability": round((success_count + 1) / (attempt_count + 2), 6),
        "concepts_per_attempt": round(accepted_concepts / attempt_count, 6) if attempt_count else None,
        "observed_call_seconds": round(sum(latencies), 6),
        "mean_call_seconds": round(sum(latencies) / len(latencies), 6) if latencies else None,
        "max_call_seconds": round(max(latencies), 6) if latencies else None,
        "latency_observations": len(latencies),
    }


def build_provider_utility_from_rows(rows: Iterable[dict], *, sources: Iterable[str] = ()) -> dict:
    """Aggregate provider/model evidence without changing routing policy.

    Provider aliases are stage-local, while model IDs are stable across primary,
    rescue, build, and critic configurations. We therefore retain both views.
    Circuit-open rows are scheduled work but not network attempts. Reliability uses
    a Beta(1,1) posterior mean so tiny samples are not mistaken for certainty.
    """
    rows = [dict(row) for row in rows if isinstance(row, dict)]
    by_provider: dict[str, list[dict]] = defaultdict(list)
    by_provider_role: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_model: dict[str, list[dict]] = defaultdict(list)
    by_model_role: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for row in rows:
        provider = str(row.get("provider") or "unknown")
        model = str(row.get("model") or f"unknown:{provider}")
        role = str(row.get("role") or "unknown")
        by_provider[provider].append(row)
        by_provider_role[(provider, role)].append(row)
        by_model[model].append(row)
        by_model_role[(model, role)].append(row)

    providers = {
        provider: _summary(provider_rows)
        for provider, provider_rows in sorted(by_provider.items())
    }
    provider_roles = [
        {"provider": provider, "role": role, **_summary(role_rows)}
        for (provider, role), role_rows in sorted(by_provider_role.items())
    ]
    models = {
        model: _summary(model_rows)
        for model, model_rows in sorted(by_model.items())
    }
    model_roles = [
        {"model": model, "role": role, **_summary(role_rows)}
        for (model, role), role_rows in sorted(by_model_role.items())
    ]
    return {
        "schema_version": "0.2",
        "policy": "measurement-only",
        "routing_effect": "none",
        "sources": list(sources),
        "observations": len(rows),
        "providers": providers,
        "provider_roles": provider_roles,
        "models": models,
        "model_roles": model_roles,
    }


def build_provider_utility_ledger(contribution_paths: Iterable[Path]) -> dict:
    rows: list[dict] = []
    sources: list[str] = []
    for path in contribution_paths:
        path = Path(path)
        loaded = _load_rows(path)
        if loaded:
            sources.append(str(path))
            rows.extend(loaded)
    return build_provider_utility_from_rows(rows, sources=sources)


def write_provider_utility_ledger(
    contribution_paths: Iterable[Path],
    output_path: Path,
) -> dict:
    payload = build_provider_utility_ledger(contribution_paths)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
