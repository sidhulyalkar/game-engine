from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .config import ProviderSpec
from .schema import Brief


UNIVERSAL_CRITICAL_ROLES = ("gameplay_director", "competition_judge")


def critical_roles(brief: Brief) -> list[str]:
    roles = list(UNIVERSAL_CRITICAL_ROLES)
    for category in brief.active_categories:
        roles.append(f"{category}_specialist")
    return list(dict.fromkeys(roles))


def provider_model_map(spec_groups: Iterable[Iterable[ProviderSpec]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for specs in spec_groups:
        for spec in specs:
            result[spec.name] = spec.model
    return result


def contribution_summary(contributions: list[dict[str, Any]], models: dict[str, str]) -> dict[str, Any]:
    successful = [row for row in contributions if row.get("ok")]
    covered_roles = sorted({str(row.get("role")) for row in successful if row.get("role")})
    successful_providers = sorted({str(row.get("provider")) for row in successful if row.get("provider")})
    successful_models = sorted({
        models.get(str(row.get("provider")), f"unknown:{row.get('provider')}")
        for row in successful
        if row.get("provider")
    })
    failures: dict[str, int] = {}
    for row in contributions:
        if row.get("ok"):
            continue
        error = str(row.get("error") or "unknown")
        if "Timeout" in error or "timeout" in error.lower():
            kind = "timeout"
        elif "HTTP 429" in error:
            kind = "rate_limit"
        elif "HTTP 404" in error:
            kind = "endpoint_or_model_not_found"
        elif "HTTP 5" in error:
            kind = "server_5xx"
        elif "ValueError" in error or "JSON" in error or "schema" in error.lower():
            kind = "content_or_schema"
        else:
            kind = "other"
        failures[kind] = failures.get(kind, 0) + 1
    return {
        "successful_assignments": len(successful),
        "successful_providers": successful_providers,
        "successful_models": successful_models,
        "covered_roles": covered_roles,
        "failure_classes": failures,
    }


def assess_primary_health(
    manifest: dict[str, Any],
    contributions: list[dict[str, Any]],
    specs: list[ProviderSpec],
    brief: Brief,
    deterministic_seed_count: int,
) -> dict[str, Any]:
    models = provider_model_map([specs])
    summary = contribution_summary(contributions, models)
    required = critical_roles(brief)
    covered = set(summary["covered_roles"])
    missing = [role for role in required if role not in covered]
    population_size = int(manifest.get("population_size", 0))
    winner_present = bool(manifest.get("winner_id"))
    llm_expanded_population = population_size > deterministic_seed_count

    usable = (
        bool(summary["successful_models"])
        and summary["successful_assignments"] >= 2
        and llm_expanded_population
        and winner_present
    )
    qualified = (
        usable
        and len(summary["successful_models"]) >= 2
        and summary["successful_assignments"] >= 5
        and not missing
    )
    if qualified:
        status = "qualified"
    elif usable:
        status = "degraded"
    else:
        status = "failed"

    return {
        "status": status,
        "usable": usable,
        "qualified": qualified,
        "rescue_required": status == "degraded",
        "required_roles": required,
        "covered_roles": summary["covered_roles"],
        "missing_roles": missing,
        "successful_assignments": summary["successful_assignments"],
        "successful_providers": summary["successful_providers"],
        "successful_models": summary["successful_models"],
        "failure_classes": summary["failure_classes"],
        "population_size": population_size,
        "deterministic_seed_count": deterministic_seed_count,
        "llm_expanded_population": llm_expanded_population,
        "winner_present": winner_present,
    }


def _active_rescue_roles(spec: ProviderSpec, brief: Brief) -> list[str]:
    active_specialists = {f"{category}_specialist" for category in brief.active_categories}
    return [
        role
        for role in spec.roles
        if not role.endswith("_specialist") or role in active_specialists
    ]


def build_rescue_config(
    base_specs: list[ProviderSpec],
    primary_health: dict[str, Any],
    brief: Brief,
) -> dict[str, Any]:
    """Build the smallest configured rescue roster that targets evidence gaps.

    Missing critical roles are always requested when a configured rescue model can
    cover them. If primary has fewer than two model IDs, at least one active role is
    also assigned to a novel model family so aliases of the same model cannot fake
    diversity.
    """
    missing = set(primary_health.get("missing_roles") or [])
    primary_models = set(primary_health.get("successful_models") or [])
    need_model_diversity = len(primary_models) < 2
    providers: list[dict[str, Any]] = []
    novel_family_assigned = False

    for spec in base_specs:
        active_roles = _active_rescue_roles(spec, brief)
        chosen = [role for role in active_roles if role in missing]
        is_novel = spec.model not in primary_models
        if need_model_diversity and is_novel and not novel_family_assigned and not chosen and active_roles:
            chosen = [active_roles[0]]
        if not chosen:
            continue
        if is_novel:
            novel_family_assigned = True
        payload = asdict(spec)
        payload["roles"] = list(dict.fromkeys(chosen))
        providers.append(payload)

    return {
        "providers": providers,
        "rescue_reason": {
            "missing_roles": sorted(missing),
            "need_model_diversity": need_model_diversity,
            "primary_models": sorted(primary_models),
        },
    }


def assess_combined_health(
    contribution_sets: Iterable[list[dict[str, Any]]],
    spec_groups: Iterable[list[ProviderSpec]],
    brief: Brief,
) -> dict[str, Any]:
    contribution_sets = list(contribution_sets)
    spec_groups = list(spec_groups)
    models = provider_model_map(spec_groups)
    combined = [row for rows in contribution_sets for row in rows]
    summary = contribution_summary(combined, models)
    required = critical_roles(brief)
    covered = set(summary["covered_roles"])
    missing = [role for role in required if role not in covered]
    qualified = (
        len(summary["successful_models"]) >= 2
        and summary["successful_assignments"] >= 5
        and not missing
    )
    return {
        "status": "qualified" if qualified else "failed",
        "qualified": qualified,
        "required_roles": required,
        "covered_roles": summary["covered_roles"],
        "missing_roles": missing,
        "successful_assignments": summary["successful_assignments"],
        "successful_providers": summary["successful_providers"],
        "successful_models": summary["successful_models"],
        "failure_classes": summary["failure_classes"],
    }


def load_contributions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"contributions must be a list: {path}")
    return [row for row in payload if isinstance(row, dict)]
