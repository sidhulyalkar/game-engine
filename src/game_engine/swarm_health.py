from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .config import ProviderSpec, load_provider_specs
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
        lowered = error.lower()
        if "timeout" in lowered:
            kind = "timeout"
        elif "http 429" in lowered:
            kind = "rate_limit"
        elif "http 404" in lowered or "not found" in lowered:
            kind = "endpoint_or_model_not_found"
        elif "http 5" in lowered:
            kind = "server_5xx"
        elif "valueerror" in lowered or "json" in lowered or "schema" in lowered or "exceeds" in lowered:
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


def write_primary_health_plan(
    brief: Brief,
    manifest_path: Path,
    contributions_path: Path,
    primary_specs_path: Path,
    rescue_specs_path: Path,
    output_dir: Path,
    deterministic_seed_count: int,
) -> dict[str, Any]:
    """Persist primary health and the smallest rescue configuration.

    A degraded primary is a valid intermediate result. It may advance only to rescue,
    never directly to concept selection. A truly unusable primary fails closed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text())
    primary_specs = load_provider_specs(primary_specs_path)
    rescue_specs = load_provider_specs(rescue_specs_path)
    contributions = load_contributions(contributions_path)
    health = assess_primary_health(
        manifest,
        contributions,
        primary_specs,
        brief,
        deterministic_seed_count=deterministic_seed_count,
    )
    rescue_config = build_rescue_config(rescue_specs, health, brief)
    rescue_path = output_dir / "rescue.generated.json"
    rescue_path.write_text(json.dumps(rescue_config, indent=2) + "\n")
    health["rescue_provider_count"] = len(rescue_config["providers"])
    health["rescue_plannable"] = (not health["rescue_required"]) or bool(rescue_config["providers"])
    health["rescue_config_path"] = str(rescue_path)
    (output_dir / "primary-health.json").write_text(json.dumps(health, indent=2) + "\n")
    return health


def write_combined_health(
    brief: Brief,
    primary_contributions_path: Path,
    primary_specs_path: Path,
    output_dir: Path,
    rescue_contributions_path: Path | None = None,
    rescue_specs_path: Path | None = None,
) -> dict[str, Any]:
    """Persist the final concept-stage health after optional targeted rescue."""
    output_dir.mkdir(parents=True, exist_ok=True)
    contribution_sets = [load_contributions(primary_contributions_path)]
    spec_groups = [load_provider_specs(primary_specs_path)]
    rescue_used = False
    if rescue_contributions_path is not None and rescue_contributions_path.exists():
        if rescue_specs_path is None or not rescue_specs_path.exists():
            raise ValueError("rescue contributions exist but rescue provider config is missing")
        contribution_sets.append(load_contributions(rescue_contributions_path))
        spec_groups.append(load_provider_specs(rescue_specs_path))
        rescue_used = True
    health = assess_combined_health(contribution_sets, spec_groups, brief)
    health["rescue_used"] = rescue_used
    (output_dir / "final-health.json").write_text(json.dumps(health, indent=2) + "\n")
    return health
