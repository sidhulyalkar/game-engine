from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import build_clients, load_provider_specs
from .evidence_broker import EvidenceBroker
from .orchestrator import Studio
from .prototype import PrototypeForge
from .reality import BrowserRealityLab
from .repair_cycle import run_repair_cycle
from .schema import Brief, Concept
from .selection import write_joint_selection
from .source_audit import SourceGameplayLab
from .swarm import SwarmStudio
from .swarm_health import write_combined_health, write_primary_health_plan


class TournamentFailure(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass(slots=True)
class TournamentPaths:
    root: Path

    def child(self, name: str) -> Path:
        return self.root / name


class StageJournal:
    def __init__(self, root: Path, seed: int):
        self.root = root
        self.seed = seed
        self.started_at = time.time()
        self.rows: list[dict[str, Any]] = []
        self.root.mkdir(parents=True, exist_ok=True)
        self._write()

    def record(self, stage: str, stage_status: str, **details: Any) -> None:
        row = {
            "stage": stage,
            "status": stage_status,
            "at_seconds": round(time.time() - self.started_at, 3),
        }
        row.update(details)
        self.rows.append(row)
        self._write()
        print(f"[studio:{stage_status}] {stage}")
        if details:
            print(json.dumps(details, indent=2, default=str))

    def _write(self) -> None:
        (self.root / "stage-journal.json").write_text(json.dumps({
            "seed": self.seed,
            "stages": self.rows,
        }, indent=2, default=str) + "\n")

    def fail(self, stage: str, message: str) -> None:
        self.record(stage, "failed", message=message)
        (self.root / "failure.json").write_text(json.dumps({
            "stage": stage,
            "message": message,
            "seed": self.seed,
            "elapsed_seconds": round(time.time() - self.started_at, 3),
        }, indent=2) + "\n")


def _load_brief(path: Path) -> Brief:
    return Brief.from_dict(json.loads(path.read_text()))


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _result_payload(result: object) -> dict[str, Any]:
    try:
        return asdict(result)
    except TypeError:
        slots = getattr(result, "__slots__", [])
        return {key: getattr(result, key) for key in slots}


def _good_builds(paths: TournamentPaths) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    good: list[tuple[str, dict[str, Any]]] = []
    failures: list[str] = []
    for race in ("a", "b"):
        path = paths.child(f"builds-{race}") / "builds.json"
        if not path.exists():
            failures.append(f"builds-{race}: missing builds.json")
            continue
        for row in _rows(path):
            if row.get("ok"):
                good.append((race, row))
            else:
                failures.append(f"{race}/{row.get('provider')}: {row.get('error')}")
    return good, failures


def _cross_browser_field(paths: TournamentPaths) -> tuple[list[tuple[str, str]], dict[str, Any], list[str]]:
    full_pass: list[tuple[str, str]] = []
    matrices: dict[str, Any] = {}
    semantic_divergence: list[str] = []
    for race in ("a", "b"):
        q_path = paths.child(f"reality-{race}") / "qualification.json"
        if not q_path.exists():
            continue
        q = json.loads(q_path.read_text())
        matrices[race] = q.get("matrix", {})
        full_pass.extend((race, str(build_id)) for build_id in q.get("full_pass_build_ids", []))
        semantic_divergence.extend(
            f"{race}:{build_id}" for build_id in q.get("semantic_divergence_build_ids", [])
        )
    return full_pass, matrices, sorted(set(semantic_divergence))


def _behavioral_field(
    paths: TournamentPaths,
) -> tuple[list[tuple[str, str]], list[str], list[str], dict[str, Any], dict[str, Any]]:
    qualified: list[tuple[str, str]] = []
    repair: list[str] = []
    insufficient: list[str] = []
    matrix: dict[str, Any] = {}
    probe_errors: dict[str, Any] = {}
    for race in ("a", "b"):
        summary_path = paths.child(f"behavior-{race}") / "evidence-broker.json"
        if not summary_path.exists():
            continue
        payload = json.loads(summary_path.read_text())
        matrix[race] = payload.get("decisions", [])
        qualified.extend(
            (race, str(build_id))
            for build_id in payload.get("behaviorally_qualified_build_ids", [])
        )
        repair.extend(
            f"{race}:{build_id}"
            for build_id in payload.get("behavioral_repair_build_ids", [])
        )
        insufficient.extend(
            f"{race}:{build_id}"
            for build_id in payload.get("insufficient_evidence_build_ids", [])
        )
        errors = payload.get("probe_errors") or {}
        if errors:
            probe_errors[race] = errors
    return (
        qualified,
        sorted(set(repair)),
        sorted(set(insufficient)),
        matrix,
        probe_errors,
    )


def _critic_reality_root(paths: TournamentPaths, race: str) -> Path:
    behavioral = paths.child(f"behavior-{race}") / "critic-reality"
    if (behavioral / "qualification.json").exists():
        return behavioral
    return paths.child(f"reality-{race}")


def _audit_field(paths: TournamentPaths) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    qualified: list[tuple[str, dict[str, Any]]] = []
    matrix: dict[str, Any] = {}
    for race in ("a", "b"):
        q_path = _critic_reality_root(paths, race) / "qualification.json"
        a_path = paths.child(f"audit-{race}") / "audit-summary.json"
        if not q_path.exists() or not a_path.exists():
            continue
        allowed = {str(value) for value in json.loads(q_path.read_text()).get("full_pass_build_ids", [])}
        audit = json.loads(a_path.read_text())
        rows = [row for row in audit.get("ranking", []) if str(row.get("build_id")) in allowed]
        matrix[race] = rows
        qualified.extend((race, row) for row in rows if int(row.get("critic_count", 0)) >= 2)
    return qualified, matrix


def _validate_secret(spec_paths: list[Path]) -> None:
    env_names: set[str] = set()
    for path in spec_paths:
        for spec in load_provider_specs(path):
            env_names.add(spec.api_key_env)
    missing = sorted(name for name in env_names if not os.environ.get(name))
    if missing:
        raise TournamentFailure("configuration", "missing API key environment variables: " + ", ".join(missing))


def _browser_install_command(browsers: tuple[str, ...]) -> list[str]:
    if not browsers:
        raise ValueError("at least one browser is required")
    return [sys.executable, "-m", "playwright", "install", "--with-deps", *browsers]


def _install_browser_engines(browsers: tuple[str, ...]) -> None:
    try:
        subprocess.run(_browser_install_command(browsers), check=True)
    except subprocess.CalledProcessError as exc:
        raise TournamentFailure(
            "browser-engine-install",
            f"Playwright browser installation failed with exit code {exc.returncode}",
        ) from exc


def run_autonomous_tournament(
    brief_path: Path,
    output_root: Path,
    seed: int,
    primary_providers: Path = Path("studio.nvidia.json"),
    rescue_providers: Path = Path("studio.nvidia.rescue.json"),
    build_providers: Path = Path("studio.nvidia.build.json"),
    audit_providers: Path = Path("studio.nvidia.audit.json"),
    repair_providers: Path = Path("studio.nvidia.repair.json"),
    browsers: tuple[str, ...] = ("chromium", "firefox", "webkit"),
    install_browsers_on_demand: bool = False,
) -> dict[str, Any]:
    paths = TournamentPaths(output_root)
    journal = StageJournal(output_root, seed)
    brief = _load_brief(brief_path)
    config_paths = [primary_providers, rescue_providers, build_providers, audit_providers, repair_providers]

    try:
        _validate_secret(config_paths)
        journal.record(
            "configuration",
            "passed",
            primary_category=brief.primary_category,
            active_categories=brief.active_categories,
            expansion_categories=brief.expansion_categories,
        )

        deterministic = Studio(seed=seed).run(brief, paths.child("deterministic"), count=32)
        journal.record("deterministic-exploration", "passed", population_size=deterministic["population_size"])

        primary_specs = load_provider_specs(primary_providers)
        primary_manifest = SwarmStudio(build_clients(primary_specs), seed=seed, max_workers=6).run(
            brief,
            paths.child("swarm-primary"),
            deterministic_seeds=24,
            concepts_per_call=3,
        )
        journal.record(
            "primary-swarm",
            "completed",
            successful_assignments=primary_manifest.get("successful_assignments"),
            failed_assignments=primary_manifest.get("failed_assignments"),
            population_size=primary_manifest.get("population_size"),
        )

        health_dir = paths.child("swarm-health")
        primary_health = write_primary_health_plan(
            brief,
            paths.child("swarm-primary") / "manifest.json",
            paths.child("swarm-primary") / "contributions.json",
            primary_providers,
            rescue_providers,
            health_dir,
            deterministic_seed_count=24,
        )
        journal.record("primary-health", primary_health["status"], **primary_health)
        if not primary_health["usable"]:
            raise TournamentFailure("primary-health", f"primary swarm is unusable: {primary_health}")
        if primary_health["rescue_required"] and not primary_health["rescue_plannable"]:
            raise TournamentFailure("primary-health", f"primary requires rescue but no configured rescue can repair it: {primary_health}")

        rescue_used = False
        generated_rescue = health_dir / "rescue.generated.json"
        rescue_contributions: Path | None = None
        if primary_health["rescue_required"]:
            rescue_specs = load_provider_specs(generated_rescue)
            rescue_manifest = SwarmStudio(build_clients(rescue_specs), seed=seed + 1009, max_workers=2).run(
                brief,
                paths.child("swarm-rescue"),
                deterministic_seeds=8,
                concepts_per_call=1,
            )
            rescue_contributions = paths.child("swarm-rescue") / "contributions.json"
            rescue_used = True
            journal.record(
                "targeted-rescue",
                "completed",
                successful_assignments=rescue_manifest.get("successful_assignments"),
                failed_assignments=rescue_manifest.get("failed_assignments"),
                population_size=rescue_manifest.get("population_size"),
            )
        else:
            journal.record("targeted-rescue", "skipped", reason="primary evidence already qualified")

        final_health = write_combined_health(
            brief,
            paths.child("swarm-primary") / "contributions.json",
            primary_providers,
            health_dir,
            rescue_contributions_path=rescue_contributions,
            rescue_specs_path=generated_rescue if rescue_used else None,
        )
        journal.record("final-swarm-health", final_health["status"], **final_health)
        if not final_health["qualified"]:
            raise TournamentFailure("final-swarm-health", f"concept evidence did not reach role/assignment quorum: {final_health}")

        sources = {"primary": paths.child("swarm-primary") / "leaderboard.json"}
        if rescue_used:
            sources["rescue"] = paths.child("swarm-rescue") / "leaderboard.json"
        selection = write_joint_selection(brief, sources, paths.child("champion"), top_k_per_source=8)
        journal.record(
            "joint-finalist-selection",
            "passed",
            source=selection.get("source"),
            score=selection.get("score"),
            score_scope=selection.get("score_scope"),
        )

        winner_payload = json.loads((paths.child("champion") / "winner.json").read_text())
        concept = Concept.from_dict(winner_payload["concept"])
        builder_specs = load_provider_specs(build_providers)
        builder_clients = build_clients(builder_specs)
        for race in ("a", "b"):
            results = PrototypeForge(builder_clients, max_workers=2).build(
                brief,
                concept,
                paths.child(f"builds-{race}"),
            )
            payload = [_result_payload(result) for result in results]
            journal.record(
                f"prototype-race-{race}",
                "completed",
                survivors=sum(bool(row.get("ok")) for row in payload),
                failures=[row.get("error") for row in payload if not row.get("ok")],
            )

        good, build_failures = _good_builds(paths)
        if not good:
            raise TournamentFailure("implementation-field", f"no byte-qualified implementation survived: {build_failures}")
        journal.record(
            "implementation-field",
            "passed",
            survivors=len(good),
            builds=[{"race": race, "provider": row.get("provider"), "bytes": row.get("compressed_bytes")} for race, row in good],
        )

        if install_browsers_on_demand:
            journal.record("browser-engine-install", "started", browsers=list(browsers))
            _install_browser_engines(browsers)
            journal.record("browser-engine-install", "passed", browsers=list(browsers))
        else:
            journal.record("browser-engine-install", "skipped", reason="caller-managed browser binaries")

        for race in ("a", "b"):
            if not any(item_race == race for item_race, _ in good):
                journal.record(f"browser-reality-{race}", "skipped", reason="no byte-qualified build in race")
                continue
            try:
                reality = BrowserRealityLab(browsers=browsers, timeout_ms=12_000).run(
                    paths.child(f"builds-{race}"),
                    paths.child(f"reality-{race}"),
                )
                journal.record(
                    f"browser-reality-{race}",
                    "completed",
                    full_pass_build_ids=reality.get("full_pass_build_ids", []),
                    semantic_divergence_build_ids=reality.get("semantic_divergence_build_ids", []),
                )
            except Exception as exc:
                journal.record(f"browser-reality-{race}", "error", error=f"{type(exc).__name__}: {exc}")

        full_pass, matrices, semantic_divergence = _cross_browser_field(paths)
        if not full_pass:
            raise TournamentFailure("cross-browser-field", f"no implementation passed all browsers: {matrices}")
        journal.record("cross-browser-field", "passed", survivors=[f"{race}:{build}" for race, build in full_pass])

        for race in ("a", "b"):
            reality_path = paths.child(f"reality-{race}") / "qualification.json"
            if not reality_path.exists() or not json.loads(reality_path.read_text()).get("full_pass_build_ids"):
                journal.record(f"behavioral-evidence-{race}", "skipped", reason="no cross-browser survivor in race")
                continue
            try:
                behavioral = EvidenceBroker(
                    browsers=("chromium",),
                    sample_interval_ms=160,
                ).run(
                    paths.child(f"builds-{race}"),
                    paths.child(f"behavior-{race}"),
                    paths.child(f"reality-{race}"),
                )
                journal.record(
                    f"behavioral-evidence-{race}",
                    "completed",
                    behaviorally_qualified_build_ids=behavioral.get("behaviorally_qualified_build_ids", []),
                    behavioral_repair_build_ids=behavioral.get("behavioral_repair_build_ids", []),
                    insufficient_evidence_build_ids=behavioral.get("insufficient_evidence_build_ids", []),
                    probe_errors=behavioral.get("probe_errors", {}),
                )
            except Exception as exc:
                journal.record(f"behavioral-evidence-{race}", "error", error=f"{type(exc).__name__}: {exc}")

        (
            behaviorally_qualified,
            behavioral_repair,
            behavioral_insufficient,
            behavioral_matrix,
            behavioral_probe_errors,
        ) = _behavioral_field(paths)
        if not behaviorally_qualified:
            if behavioral_repair:
                raise TournamentFailure(
                    "behavioral-evidence",
                    "cross-browser builds require targeted behavioral repair before LLM criticism: "
                    + json.dumps({
                        "repair_build_ids": behavioral_repair,
                        "insufficient_evidence_build_ids": behavioral_insufficient,
                        "probe_errors": behavioral_probe_errors,
                    }),
                )
            raise TournamentFailure(
                "behavioral-evidence",
                "no cross-browser implementation produced complete causal gameplay evidence: "
                + json.dumps({
                    "insufficient_evidence_build_ids": behavioral_insufficient,
                    "probe_errors": behavioral_probe_errors,
                    "matrix": behavioral_matrix,
                }),
            )
        journal.record(
            "behavioral-evidence",
            "passed",
            survivors=[f"{race}:{build}" for race, build in behaviorally_qualified],
            repair_build_ids=behavioral_repair,
            insufficient_evidence_build_ids=behavioral_insufficient,
            probe_errors=behavioral_probe_errors,
        )

        selection_payload = json.loads((paths.child("champion") / "selection.json").read_text())
        good_rows = [row for _, row in good]
        run_summary: dict[str, Any] = {
            "concept": concept.title,
            "concept_id": concept.concept_id,
            "concept_source": selection_payload["source"],
            "concept_score": selection_payload["score"],
            "concept_score_scope": selection_payload.get("score_scope"),
            "primary_health": primary_health,
            "final_swarm_health": final_health,
            "rescue_used": rescue_used,
            "prototype_survivors": len(good),
            "cross_browser_survivors": len(full_pass),
            "cross_browser_build_ids": [f"{race}:{build}" for race, build in full_pass],
            "browser_matrices": matrices,
            "semantic_divergence_build_ids": semantic_divergence,
            "smallest_survivor_bytes": min(row["compressed_bytes"] for row in good_rows),
            "largest_headroom_bytes": max(row["byte_headroom"] for row in good_rows),
            "browser_reality_lab_passed": True,
            "behavioral_evidence_lab_passed": True,
            "behavioral_reference_browser": "chromium",
            "behaviorally_qualified_build_ids": [
                f"{race}:{build}" for race, build in behaviorally_qualified
            ],
            "behavioral_repair_build_ids": behavioral_repair,
            "behavioral_insufficient_evidence_build_ids": behavioral_insufficient,
            "behavioral_probe_errors": behavioral_probe_errors,
            "behavioral_matrix": behavioral_matrix,
            "competitive_field": len(behaviorally_qualified) >= 2,
            "promotion_blocked_until_gameplay_audit": True,
        }
        (output_root / "run-summary.json").write_text(json.dumps(run_summary, indent=2) + "\n")

        audit_specs = load_provider_specs(audit_providers)
        audit_clients = build_clients(audit_specs)
        for race in ("a", "b"):
            critic_reality = _critic_reality_root(paths, race)
            qualification_path = critic_reality / "qualification.json"
            if not qualification_path.exists() or not json.loads(qualification_path.read_text()).get("full_pass_build_ids"):
                journal.record(f"source-audit-{race}", "skipped", reason="no behaviorally qualified build in race")
                continue
            try:
                audit = SourceGameplayLab(audit_clients, max_workers=4).run(
                    brief,
                    concept,
                    paths.child(f"builds-{race}"),
                    paths.child(f"audit-{race}"),
                    critic_reality,
                )
                journal.record(
                    f"source-audit-{race}",
                    "completed",
                    advance_build_ids=audit.get("advance_build_ids", []),
                    repair_build_ids=audit.get("repair_build_ids", []),
                    reject_build_ids=audit.get("reject_build_ids", []),
                )
            except Exception as exc:
                journal.record(f"source-audit-{race}", "error", error=f"{type(exc).__name__}: {exc}")

        qualified_audits, audit_matrix = _audit_field(paths)
        if not qualified_audits:
            raise TournamentFailure("gameplay-audit-evidence", f"no behaviorally qualified build received two independent audits: {audit_matrix}")
        journal.record("gameplay-audit-evidence", "passed", qualified=len(qualified_audits))
        run_summary["gameplay_audit_evidence"] = True
        run_summary["gameplay_audit_matrix"] = audit_matrix
        run_summary["gameplay_advance_build_ids"] = [f"{race}:{row['build_id']}" for race, row in qualified_audits if row.get("status") == "advance"]
        run_summary["gameplay_repair_build_ids"] = [f"{race}:{row['build_id']}" for race, row in qualified_audits if row.get("status") == "repair"]
        run_summary["gameplay_reject_build_ids"] = [f"{race}:{row['build_id']}" for race, row in qualified_audits if row.get("status") == "reject"]
        run_summary["promotion_blocked_until_repair_and_playtest_loop"] = True
        run_summary.pop("promotion_blocked_until_gameplay_audit", None)
        (output_root / "run-summary.json").write_text(json.dumps(run_summary, indent=2) + "\n")

        cycle_summaries: dict[str, Any] = {}
        repairable = 0
        for race in ("a", "b"):
            audit_summary_path = paths.child(f"audit-{race}") / "audit-summary.json"
            if not audit_summary_path.exists():
                continue
            audit_summary = json.loads(audit_summary_path.read_text())
            repair_ids = audit_summary.get("repair_build_ids", [])
            repairable += len(repair_ids)
            if not repair_ids:
                journal.record(f"repair-cycle-{race}", "skipped", reason="no repair candidates")
                continue
            try:
                cycle = run_repair_cycle(
                    paths.child("champion") / "winner.json",
                    paths.child(f"builds-{race}"),
                    paths.child(f"audit-{race}"),
                    repair_providers,
                    audit_providers,
                    paths.child(f"repair-cycle-{race}"),
                    browsers=list(browsers),
                    max_parents=1,
                    workers=4,
                    timeout_ms=12_000,
                )
                cycle_summaries[race] = cycle
                journal.record(f"repair-cycle-{race}", cycle.get("status", "completed"), summary=cycle)
            except Exception as exc:
                journal.record(f"repair-cycle-{race}", "error", error=f"{type(exc).__name__}: {exc}")

        if repairable and not cycle_summaries:
            raise TournamentFailure("repair-cycle-evidence", "repairable parents existed but no repair-cycle evidence was produced")
        failed_cycles = {
            race: row for race, row in cycle_summaries.items()
            if row.get("status") not in {"complete", "no_repair_candidates"}
        }
        if failed_cycles:
            raise TournamentFailure("repair-cycle-evidence", f"repair-cycle infrastructure/evidence failure: {failed_cycles}")

        improving = [
            f"{race}:{build_id}"
            for race, row in cycle_summaries.items()
            for build_id in row.get("evidence_improving_children", [])
        ]
        run_summary["repairable_parent_count"] = repairable
        run_summary["repair_cycle_evidence"] = cycle_summaries
        run_summary["evidence_improving_children"] = improving
        run_summary["lineage_improved_this_run"] = bool(improving)
        run_summary["promotion_blocked_until_agentic_and_player_facing_playtests"] = True
        run_summary.pop("promotion_blocked_until_repair_and_playtest_loop", None)
        (output_root / "run-summary.json").write_text(json.dumps(run_summary, indent=2) + "\n")
        journal.record("tournament", "completed", lineage_improved=bool(improving), repairable_parents=repairable)
        return run_summary
    except TournamentFailure as exc:
        journal.fail(exc.stage, exc.message)
        raise
    except Exception as exc:
        journal.fail("unclassified-infrastructure", f"{type(exc).__name__}: {exc}")
        raise TournamentFailure("unclassified-infrastructure", f"{type(exc).__name__}: {exc}") from exc
