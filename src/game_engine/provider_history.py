from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .provider_performance import compile_provider_performance


def _posterior(successes: int, attempts: int) -> float | None:
    if attempts < 0 or successes < 0 or successes > attempts:
        raise ValueError("invalid success/attempt counts")
    if attempts == 0:
        return None
    return round((successes + 1) / (attempts + 2), 6)


def _record() -> dict[str, Any]:
    return {
        "runs_observed": set(),
        "ideation": {
            "assignments": 0,
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "skipped": 0,
            "concepts_generated": 0,
            "failure_classes": defaultdict(int),
            "roles": defaultdict(lambda: {
                "assignments": 0,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "skipped": 0,
            }),
            "latency_observations": 0,
            "observed_call_seconds": 0.0,
        },
        "builder": {"attempts": 0, "successes": 0, "failures": 0},
        "critics": {"attempts": 0, "successes": 0, "failures": 0},
        "repairs": {
            "behavioral_attempts": 0,
            "behavioral_successes": 0,
            "critic_repair_attempts": 0,
            "critic_repair_successes": 0,
        },
        "downstream": defaultdict(int),
    }


def compile_provider_history(
    run_roots: Iterable[Path],
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Aggregate provider evidence across tournaments without global ranking.

    The history is intentionally phase- and role-specific. A model that is an
    excellent builder but unreliable critic is not collapsed into one scalar score.
    Beta(1,1) posterior means are descriptive uncertainty-aware summaries only; this
    module has no routing authority.
    """
    runs = [Path(root) for root in run_roots]
    providers: defaultdict[str, dict[str, Any]] = defaultdict(_record)
    observed_runs: list[str] = []

    for run_root in runs:
        performance = compile_provider_performance(run_root)
        if not performance.get("providers"):
            continue
        run_id = run_root.name
        observed_runs.append(str(run_root))
        for provider, row in performance["providers"].items():
            target = providers[provider]
            target["runs_observed"].add(run_id)

            idea = row["ideation"]
            target_idea = target["ideation"]
            assignments = int(idea.get("assignments", 0))
            skipped = int(idea.get("skipped", 0))
            target_idea["assignments"] += assignments
            target_idea["attempts"] += assignments - skipped
            target_idea["successes"] += int(idea.get("successes", 0))
            target_idea["failures"] += int(idea.get("failures", 0))
            target_idea["skipped"] += skipped
            target_idea["concepts_generated"] += int(idea.get("concepts_generated", 0))
            target_idea["latency_observations"] += int(idea.get("latency_observations", 0))
            target_idea["observed_call_seconds"] += float(idea.get("observed_call_seconds", 0.0))
            for kind, count in (idea.get("failure_classes") or {}).items():
                target_idea["failure_classes"][str(kind)] += int(count)
            for role, role_row in (idea.get("roles") or {}).items():
                role_target = target_idea["roles"][str(role)]
                role_assignments = int(role_row.get("assignments", 0))
                role_skipped = int(role_row.get("skipped", 0))
                role_target["assignments"] += role_assignments
                role_target["attempts"] += role_assignments - role_skipped
                role_target["successes"] += int(role_row.get("successes", 0))
                role_target["failures"] += int(role_row.get("failures", 0))
                role_target["skipped"] += role_skipped

            builder = row["builder"]
            for key in ("attempts", "successes", "failures"):
                target["builder"][key] += int(builder.get(key, 0))

            critics = row["critics"]
            target["critics"]["attempts"] += int(critics.get("calls", 0))
            target["critics"]["successes"] += int(critics.get("successes", 0))
            target["critics"]["failures"] += int(critics.get("failures", 0))

            repairs = row["repairs"]
            for key in target["repairs"]:
                target["repairs"][key] += int(repairs.get(key, 0))

            for key, count in row["downstream"].items():
                target["downstream"][key] += int(count)

    normalized: dict[str, Any] = {}
    for provider, record in sorted(providers.items()):
        idea = record["ideation"]
        role_rows = {}
        for role, role in sorted(idea["roles"].items()):
            role = dict(role)
            role["smoothed_reliability"] = _posterior(role["successes"], role["attempts"])
            role_rows[role if isinstance(role, str) else ""] = role
        # The loop variable above intentionally cannot serve as the role name after
        # conversion. Rebuild deterministically from the original mapping instead.
        role_rows = {}
        for role_name, role_value in sorted(idea["roles"].items()):
            role_value = dict(role_value)
            role_value["smoothed_reliability"] = _posterior(
                role_value["successes"], role_value["attempts"]
            )
            role_rows[role_name] = role_value

        idea_payload = {
            key: value
            for key, value in idea.items()
            if key not in {"roles", "failure_classes"}
        }
        idea_payload["observed_call_seconds"] = round(idea_payload["observed_call_seconds"], 6)
        idea_payload["mean_call_seconds"] = (
            round(idea_payload["observed_call_seconds"] / idea_payload["latency_observations"], 6)
            if idea_payload["latency_observations"]
            else None
        )
        idea_payload["smoothed_reliability"] = _posterior(
            idea_payload["successes"], idea_payload["attempts"]
        )
        idea_payload["failure_classes"] = dict(sorted(idea["failure_classes"].items()))
        idea_payload["roles"] = role_rows

        builder = dict(record["builder"])
        builder["smoothed_reliability"] = _posterior(builder["successes"], builder["attempts"])
        critics = dict(record["critics"])
        critics["smoothed_reliability"] = _posterior(critics["successes"], critics["attempts"])

        normalized[provider] = {
            "runs_observed": sorted(record["runs_observed"]),
            "run_count": len(record["runs_observed"]),
            "ideation": idea_payload,
            "builder": builder,
            "critics": critics,
            "repairs": dict(record["repairs"]),
            "downstream": dict(sorted(record["downstream"].items())),
        }

    payload = {
        "schema_version": "0.1",
        "mode": "longitudinal-shadow",
        "routing_authority": False,
        "run_roots": observed_runs,
        "run_count": len(observed_runs),
        "providers": normalized,
        "interpretation_boundary": (
            "Phase/role reliability summarizes observed infrastructure behavior only. "
            "It is not a global model-quality score and cannot waive coverage or evidence gates."
        ),
    }
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
