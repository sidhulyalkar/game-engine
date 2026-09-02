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


def _legacy_failure_class(row: dict[str, Any]) -> str:
    error = str(row.get("error") or "unknown")
    lowered = error.lower()
    if "timeout" in lowered or "transport failure" in lowered:
        return "transport"
    if "http 429" in lowered:
        return "rate_limit"
    if "http 404" in lowered or "not found" in lowered:
        return "endpoint_or_model_not_found"
    if "http 5" in lowered:
        return "server_5xx"
    if "valueerror" in lowered or "json" in lowered or "schema" in lowered or "exceeds" in lowered:
        return "content_or_schema"
    return "other"


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
    skipped: dict[str, int] = {}
    for row in contributions:
        if row.get("ok"):
            continue
        explicit = str(row.get("failure_class") or "").strip()
        kind = explicit or _legacy_failure_class(row)
        target = skipped if row.get("skipped") else failures
        target[kind] = target.get(kind, 0) + 1
    return {
        "successful_assignments": len(successful),
        "successful_providers": successful_providers,
        "successful_models": successful_models,
        "covered_roles": covered_roles,
        "failure_classes": failures,
        "skipped_classes": skipped,
        "skipped_assignments": sum(skipped.values()),
    }


def _diversity_fields(summary: dict[str, Any]) -> dict[str, Any]:
    model_count = len(summary["successful_models"])
    heterogeneous = model_count >= 2
    return {
        "model_family_count": model_count,
        "heterogeneous_models": heterogeneous,
        "diversity_shortfall": model_count < 2,
        "evidence_confidence": "heterogeneous" if heterogeneous else ("single-family" if model_count else "none"),
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
    diversity = _diversity_fields(summary)

    usable = (
        bool(summary["successful_models"])
        and summary["successful_assignments"] >= 2
        and llm_expanded_population
        and winner_present
    )
    coverage_quorum = (
        usable
        and summary["successful_assignments"] >= 5
        and not missing
    )
    fully_qualified = coverage_quorum and diversity["heterogeneous_models"]
    if fully_qualified:
        status = "qualified"
    elif usable:
        status = "degraded"
    else:
        status = "failed"

    return {
        "status": status,
        "usable": usable,
        "qualified": fully_qualified,
        "coverage_quorum": coverage_quorum,
        "rescue_required": status == "degraded",
        "required_roles": required,
        "covered_roles": summary["covered_roles"],
        "missing_roles": missing,
        "successful_assignments": summary["successful_assignments"],
        "successful_providers": summary["successful_providers"],
        "successful_models": summary["successful_models"],
        "failure_classes": summary["failure_classes"],
        "skipped_classes": summary["skipped_classes"],
        "skipped_assignments": summary["skipped_assignments"],
        "population_size": population_size,
        "deterministic_seed_count": deterministic_seed_count,
        "llm_expanded_population": llm_expanded_population,
        "winner_present": winner_present,
        **diversity,
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
    """Build a bounded rescue roster for missing critical evidence and diversity.

    Every missing gate-critical role receives up to two distinct configured model
    families when available, including the active medium specialist. This prevents a
    single remote family from being the only keyholder for Desktop/Online/WebXR
    qualification. Model-family diversity is still pursued, but the final health gate
    treats it as confidence evidence rather than discarding complete role coverage
    during a partial provider outage.
    """
    missing_order = [str(role) for role in primary_health.get("missing_roles") or []]
    missing = set(missing_order)
    critical = set(critical_roles(brief))
    primary_models = set(primary_health.get("successful_models") or [])
    successful_assignments = int(primary_health.get("successful_assignments", 0))
    need_model_diversity = len(primary_models) < 2

    active_by_name = {spec.name: _active_rescue_roles(spec, brief) for spec in base_specs}
    selected: dict[str, list[str]] = {spec.name: [] for spec in base_specs}

    def add(spec: ProviderSpec, role: str) -> bool:
        if role not in active_by_name[spec.name] or role in selected[spec.name]:
            return False
        selected[spec.name].append(role)
        return True

    redundant_roles: list[str] = []
    for role in missing_order:
        candidates = [spec for spec in base_specs if role in active_by_name[spec.name]]
        candidates.sort(key=lambda spec: (spec.model in primary_models, spec.name))
        target_models = 2 if role in critical else 1
        seen_models: set[str] = set()
        for spec in candidates:
            if spec.model in seen_models:
                continue
            if add(spec, role):
                seen_models.add(spec.model)
            if len(seen_models) >= target_models:
                break
        if role in critical and len(seen_models) >= 2:
            redundant_roles.append(role)

    def selected_specs() -> list[ProviderSpec]:
        names = {name for name, roles in selected.items() if roles}
        return [spec for spec in base_specs if spec.name in names]

    # If role coverage is already complete but the primary has only one model family,
    # spend at most one bounded call on an independently configured model. This is an
    # evidence-quality upgrade, not a hard requirement for final concept-stage health.
    if need_model_diversity and not any(spec.model not in primary_models for spec in selected_specs()):
        novel = [spec for spec in base_specs if spec.model not in primary_models and active_by_name[spec.name]]
        novel.sort(key=lambda spec: spec.name)
        if novel:
            spec = novel[0]
            preferred = [role for role in missing_order if role in active_by_name[spec.name]]
            role = preferred[0] if preferred else active_by_name[spec.name][0]
            add(spec, role)

    needed_calls = max(0, 5 - successful_assignments)
    while sum(len(roles) for roles in selected.values()) < needed_calls:
        candidates: list[tuple[bool, str, ProviderSpec, str]] = []
        for spec in base_specs:
            for role in active_by_name[spec.name]:
                if role not in selected[spec.name]:
                    candidates.append((spec.model in primary_models, spec.name, spec, role))
        if not candidates:
            break
        _, _, spec, role = sorted(candidates, key=lambda row: (row[0], row[1], row[3]))[0]
        add(spec, role)

    providers: list[dict[str, Any]] = []
    for spec in base_specs:
        roles = selected[spec.name]
        if not roles:
            continue
        payload = asdict(spec)
        payload["roles"] = roles
        providers.append(payload)

    assigned_roles = {role for roles in selected.values() for role in roles}
    uncovered_missing_roles = [role for role in missing_order if role not in assigned_roles]
    novel_model_plannable = (
        not need_model_diversity
        or any(spec.model not in primary_models for spec in selected_specs())
    )
    return {
        "providers": providers,
        "rescue_reason": {
            "missing_roles": sorted(missing),
            "uncovered_missing_roles": uncovered_missing_roles,
            "redundant_critical_roles": sorted(redundant_roles),
            "need_model_diversity": need_model_diversity,
            "novel_model_plannable": novel_model_plannable,
            "primary_models": sorted(primary_models),
            "primary_successful_assignments": successful_assignments,
            "planned_assignments": sum(len(roles) for roles in selected.values()),
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
    diversity = _diversity_fields(summary)

    # Final concept-stage qualification is a coverage quorum. Heterogeneous model
    # evidence raises confidence but cannot veto complete evidence merely because a
    # remote model family is temporarily unavailable. Downstream byte/browser/source/
    # behavioral/player-facing gates remain independent promotion blockers.
    coverage_quorum = (
        bool(summary["successful_models"])
        and summary["successful_assignments"] >= 5
        and not missing
    )
    return {
        "status": "qualified" if coverage_quorum else "failed",
        "qualified": coverage_quorum,
        "coverage_quorum": coverage_quorum,
        "required_roles": required,
        "covered_roles": summary["covered_roles"],
        "missing_roles": missing,
        "successful_assignments": summary["successful_assignments"],
        "successful_providers": summary["successful_providers"],
        "successful_models": summary["successful_models"],
        "failure_classes": summary["failure_classes"],
        "skipped_classes": summary["skipped_classes"],
        "skipped_assignments": summary["skipped_assignments"],
        **diversity,
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
    reason = rescue_config.get("rescue_reason", {})
    provider_count = len(rescue_config["providers"])
    coverage_repair_required = not bool(health.get("coverage_quorum"))
    diversity_rescue_recommended = (
        bool(health.get("coverage_quorum"))
        and bool(health.get("diversity_shortfall"))
        and provider_count > 0
        and bool(reason.get("novel_model_plannable", False))
    )
    health["rescue_provider_count"] = provider_count
    health["coverage_repair_required"] = coverage_repair_required
    health["diversity_rescue_recommended"] = diversity_rescue_recommended
    health["rescue_required"] = bool(health["usable"]) and (coverage_repair_required or diversity_rescue_recommended)
    health["rescue_plannable"] = (
        not health["rescue_required"]
        or (
            provider_count > 0
            and (not coverage_repair_required or not reason.get("uncovered_missing_roles"))
        )
    )
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
