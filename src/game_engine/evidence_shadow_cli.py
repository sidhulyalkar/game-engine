from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .evidence_director import EvidenceDirectedDirector


_DEFAULT_CONFIGS = {
    "primary": Path("studio.nvidia.json"),
    "rescue": Path("studio.nvidia.rescue.json"),
    "build": Path("studio.nvidia.build.json"),
    "audit": Path("studio.nvidia.audit.json"),
    "repair": Path("studio.nvidia.repair.json"),
}


def _candidate_evidence(run_root: Path):
    return (
        ("a", "generated-web", run_root / "staged-a" / "staged-evidence.json"),
        ("b", "generated-web", run_root / "staged-b" / "staged-evidence.json"),
        ("a", "behavioral-repair", run_root / "staged-repair-a" / "staged-evidence.json"),
        ("b", "behavioral-repair", run_root / "staged-repair-b" / "staged-evidence.json"),
        (
            "a",
            "critic-repair",
            run_root / "repair-cycle-a" / "staged-evidence" / "staged-evidence.json",
        ),
        (
            "b",
            "critic-repair",
            run_root / "repair-cycle-b" / "staged-evidence" / "staged-evidence.json",
        ),
    )


def observe_tournament_run(
    run_root: Path,
    *,
    brief_path: Path,
    seed: int,
    browsers: tuple[str, ...],
    provider_configs: dict[str, Path] | None = None,
    git_sha: str | None = None,
) -> dict:
    """Materialize shadow evidence from a completed or partially failed tournament."""
    configs = dict(provider_configs or _DEFAULT_CONFIGS)
    evidence_root = run_root / "evidence-directed"
    director = EvidenceDirectedDirector.initialize(
        evidence_root,
        brief_path=brief_path,
        provider_configs=configs,
        seed=seed,
        browsers=browsers,
        git_sha=git_sha,
    )

    observed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for race, lineage, path in _candidate_evidence(run_root):
        if not path.exists():
            skipped.append({
                "race": race,
                "lineage": lineage,
                "path": str(path),
                "reason": "artifact_not_present",
            })
            continue
        try:
            summary = director.observe_staged_evidence(
                race=race,
                staged_evidence_path=path,
                lineage=lineage,
            )
            observed.append({
                "race": race,
                "lineage": lineage,
                "path": str(path),
                "subjects": sorted(summary["observations"]),
                "scheduler_actions": {
                    build_id: row["scheduler"]["action"]
                    for build_id, row in sorted(summary["observations"].items())
                },
                "promotion_status": {
                    build_id: row["promotion"]["status"]
                    for build_id, row in sorted(summary["observations"].items())
                },
            })
        except Exception as exc:
            errors.append({
                "race": race,
                "lineage": lineage,
                "path": str(path),
                "error": f"{type(exc).__name__}: {exc}",
            })

    # Provider performance is descriptive even for partial runs. It must never make
    # this shadow observer fail merely because a later tournament stage did not run.
    try:
        provider_shadow = director.compile_provider_shadow(run_root)
        provider_error = None
    except Exception as exc:
        provider_shadow = None
        provider_error = f"{type(exc).__name__}: {exc}"

    payload = {
        "schema_version": "0.1",
        "mode": "shadow",
        "routing_authority": False,
        "experiment_fingerprint": director.identity["experiment_fingerprint"],
        "run_root": str(run_root),
        "observed": observed,
        "skipped": skipped,
        "errors": errors,
        "provider_performance_written": provider_shadow is not None,
        "provider_performance_error": provider_error,
    }
    (evidence_root / "shadow-run-summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile tournament evidence without changing routing")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--brief", type=Path, default=Path("examples/briefs/js13k-2026.json"))
    parser.add_argument("--seed", type=int, default=64)
    parser.add_argument(
        "--browsers",
        nargs="+",
        default=["chromium", "firefox", "webkit"],
    )
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = observe_tournament_run(
        args.run_root,
        brief_path=args.brief,
        seed=args.seed,
        browsers=tuple(args.browsers),
        git_sha=args.git_sha,
    )
    print(json.dumps(payload, indent=2))
    # The observer itself fails only when evidence that exists is internally
    # contradictory. Missing downstream artifacts are expected on failed runs.
    return 2 if payload["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
