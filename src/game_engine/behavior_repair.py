from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .packaging import package_game
from .prototype import _complete_with_provenance, _extract_html_response
from .providers.base import LLMClient
from .reality import discover_builds
from .schema import Brief, Concept
from .source_falsification import analyze_source


@dataclass(slots=True)
class BehavioralRepairResult:
    provider: str
    parent_build_id: str
    parent_provider: str
    build_id: str
    ok: bool
    source_dir: str | None
    zip_path: str | None
    compressed_bytes: int | None
    byte_headroom: int | None
    warnings: list[str]
    raw_response_path: str | None = None
    response_format: str | None = None
    source_falsification_path: str | None = None
    remaining_source_blockers: list[str] | None = None
    error: str | None = None


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value[:60] or "behavior-repairer"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _matching_build(rows: Any, build_id: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and str(row.get("build_id")) == build_id]


def load_behavioral_repair_candidates(
    builds_root: Path,
    behavior_root: Path,
    max_parents: int = 1,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    summary_path = behavior_root / "evidence-broker.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing behavioral evidence: {summary_path}")
    summary = json.loads(summary_path.read_text())
    decisions = {
        str(row.get("build_id")): row
        for row in summary.get("decisions", [])
        if isinstance(row, dict) and row.get("status") == "behavioral_repair"
    }
    builds = {str(row.get("build_id")): row for row in discover_builds(builds_root)}

    action = _read_json(behavior_root / "action-causality" / "action-summary.json") or {}
    restart = _read_json(behavior_root / "restart" / "restart-summary.json") or {}
    agency = _read_json(behavior_root / "agency" / "playtest-summary.json") or {}

    candidates = []
    for build_id in sorted(decisions):
        build = builds.get(build_id)
        if not build:
            continue
        bundle = {
            "decision": decisions[build_id],
            "action_causality": _matching_build(action.get("builds"), build_id),
            "restart": _matching_build(restart.get("cases"), build_id),
            "agency": _matching_build(agency.get("builds"), build_id),
            "agency_flags": {
                "independently_observable": build_id in set(agency.get("independently_observable_build_ids", [])),
                "telemetry_visual_contradiction": build_id in set(agency.get("telemetry_visual_contradiction_build_ids", [])),
            },
        }
        candidates.append((build, decisions[build_id], bundle))
    return candidates[: max(0, max_parents)]


def behavioral_repair_prompt(
    brief: Brief,
    concept: Concept,
    game_spec: dict[str, Any],
    parent: dict[str, Any],
    evidence: dict[str, Any],
    html: str,
) -> tuple[str, str]:
    system = """You are a surgical gameplay engineer repairing one existing tiny web game after causal browser probes. The design is already chosen. Fix only the observed behavioral contract failures. Preserve working mechanics, art direction, pacing, controls, and byte-efficient structure. Return ONLY one complete standalone HTML document ending in </html>. No JSON, markdown, patch, explanation, or redesign."""
    user = f"""COMPETITION BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nWINNING CONCEPT:\n{json.dumps(concept.to_dict(), indent=2)}\n\nAUTHORITATIVE GAMESPEC:\n{json.dumps(game_spec, indent=2)}\n\nPARENT BUILD METADATA:\n{json.dumps({k: v for k, v in parent.items() if k != 'resolved_source_dir'}, indent=2)}\n\nCAUSAL BROWSER EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\nCURRENT INDEX.HTML:\n{html}\n\nPerform one bounded behavioral repair. Hard rules:\n- fix every blocker in the behavioral decision, and do not add unrelated features\n- every GameSpec action marked required must remain advertised and must causally affect real gameplay beyond matched idle behavior\n- do not delete or rename a required control merely to make the probe pass\n- a restart must return mutated gameplay state to a fresh-run baseline without spawning duplicate requestAnimationFrame loops\n- active player input must create meaningful gameplay agency beyond autoplay/idle evolution\n- telemetry must describe the real gameplay state; never create a parallel fake state machine solely for the evaluator\n- telemetry reads are side-effect free and the event log remains bounded\n- preserve deterministic seed, frame-rate-independent timing, entity bounds, offline single-file behavior, and the defining interaction\n- preserve recognizable theme and feedback already working in the parent\n- remain below {brief.size_limit_bytes} compressed bytes with useful headroom\n- return the FULL repaired HTML document only\n"""
    return system, user


def _blocker_codes(report: dict[str, Any]) -> list[str]:
    return [
        str(row.get("code"))
        for row in report.get("findings") or []
        if row.get("severity") == "blocker"
    ]


class BehavioralRepairForge:
    """One bounded repair generation for builds that failed objective gameplay probes."""

    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 2):
        self.clients = clients
        self.max_workers = max_workers

    def build(
        self,
        brief: Brief,
        concept: Concept,
        builds_root: Path,
        behavior_root: Path,
        output_dir: Path,
        max_parents: int = 1,
    ) -> list[BehavioralRepairResult]:
        candidates = load_behavioral_repair_candidates(
            builds_root,
            behavior_root,
            max_parents=max_parents,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        game_spec_path = builds_root / "game-spec.json"
        if not game_spec_path.exists():
            raise FileNotFoundError(f"missing GameSpec: {game_spec_path}")
        game_spec = json.loads(game_spec_path.read_text())
        (output_dir / "game-spec.json").write_text(json.dumps(game_spec, indent=2) + "\n")

        if not candidates:
            (output_dir / "builds.json").write_text("[]\n")
            (output_dir / "behavior-repair-manifest.json").write_text(json.dumps({
                "repair_candidates": 0,
                "attempted_children": 0,
                "successful_children": 0,
            }, indent=2) + "\n")
            return []

        jobs = []
        for parent, decision, evidence in candidates:
            html = (Path(parent["resolved_source_dir"]) / "index.html").read_text()
            system, prompt = behavioral_repair_prompt(
                brief,
                concept,
                game_spec,
                parent,
                evidence,
                html,
            )
            for provider_spec, client in self.clients:
                jobs.append((provider_spec, client, parent, decision, evidence, system, prompt))

        results: list[BehavioralRepairResult] = []
        raw_dir = output_dir / "raw"
        meta_dir = output_dir / "meta"
        raw_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(_complete_with_provenance, client, system, prompt):
                    (provider_spec, client, parent, decision, evidence)
                for provider_spec, client, parent, decision, evidence, system, prompt in jobs
            }
            for future in as_completed(futures):
                provider_spec, client, parent, decision, evidence = futures[future]
                provider = getattr(provider_spec, "name", getattr(client, "name", "behavior-repairer"))
                parent_id = str(parent.get("build_id"))
                raw_path: Path | None = None
                source_path: Path | None = None
                falsification_path: Path | None = None
                build_id = "failed"
                try:
                    response, finish_reason, usage = future.result()
                    raw_digest = hashlib.sha1(response.encode()).hexdigest()[:10]
                    raw_path = raw_dir / f"{_safe_name(provider)}-{parent_id}-{raw_digest}.txt"
                    raw_path.write_text(response)
                    html, response_format = _extract_html_response(response)
                    build_id = hashlib.sha1(
                        f"behavior-repair:{provider}:{parent_id}:{html}".encode()
                    ).hexdigest()[:10]
                    source_path = output_dir / f"{_safe_name(provider)}-{parent_id}-{build_id}"
                    source_path.mkdir(parents=True, exist_ok=True)
                    (source_path / "index.html").write_text(html)

                    source_report = analyze_source(html, game_spec)
                    blockers = _blocker_codes(source_report)
                    falsification_path = meta_dir / f"{_safe_name(provider)}-{build_id}-source-falsification.json"
                    falsification_path.write_text(json.dumps(source_report, indent=2) + "\n")
                    meta_path = meta_dir / f"{_safe_name(provider)}-{build_id}.json"
                    meta_path.write_text(json.dumps({
                        "provider": provider,
                        "parent_build_id": parent_id,
                        "behavioral_decision": decision,
                        "behavioral_evidence": evidence,
                        "raw_response": str(raw_path),
                        "response_format": response_format,
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "source_falsification": source_report,
                    }, indent=2) + "\n")

                    if blockers:
                        results.append(BehavioralRepairResult(
                            provider=provider,
                            parent_build_id=parent_id,
                            parent_provider=str(parent.get("provider", "unknown")),
                            build_id=build_id,
                            ok=False,
                            source_dir=str(source_path),
                            zip_path=None,
                            compressed_bytes=None,
                            byte_headroom=None,
                            warnings=[],
                            raw_response_path=str(raw_path),
                            response_format=response_format,
                            source_falsification_path=str(falsification_path),
                            remaining_source_blockers=blockers,
                            error="SourceFalsificationError after behavioral repair: " + ", ".join(blockers),
                        ))
                        continue

                    zip_path = output_dir / "dist" / f"{_safe_name(provider)}-{build_id}.zip"
                    package = package_game(source_path, zip_path, brief.size_limit_bytes)
                    warnings = list(package.warnings)
                    results.append(BehavioralRepairResult(
                        provider=provider,
                        parent_build_id=parent_id,
                        parent_provider=str(parent.get("provider", "unknown")),
                        build_id=build_id,
                        ok=package.ok,
                        source_dir=str(source_path),
                        zip_path=str(zip_path),
                        compressed_bytes=package.compressed_bytes,
                        byte_headroom=brief.size_limit_bytes - package.compressed_bytes,
                        warnings=warnings,
                        raw_response_path=str(raw_path),
                        response_format=response_format,
                        source_falsification_path=str(falsification_path),
                        remaining_source_blockers=[],
                        error=None if package.ok else "compressed byte limit exceeded",
                    ))
                except Exception as exc:
                    results.append(BehavioralRepairResult(
                        provider=provider,
                        parent_build_id=parent_id,
                        parent_provider=str(parent.get("provider", "unknown")),
                        build_id=build_id,
                        ok=False,
                        source_dir=str(source_path) if source_path else None,
                        zip_path=None,
                        compressed_bytes=None,
                        byte_headroom=None,
                        warnings=[],
                        raw_response_path=str(raw_path) if raw_path else None,
                        response_format=None,
                        source_falsification_path=str(falsification_path) if falsification_path else None,
                        remaining_source_blockers=None,
                        error=f"{type(exc).__name__}: {exc}",
                    ))

        results.sort(key=lambda row: (not row.ok, -(row.byte_headroom or -10**9), row.provider))
        (output_dir / "builds.json").write_text(json.dumps([asdict(row) for row in results], indent=2) + "\n")
        (output_dir / "behavior-repair-manifest.json").write_text(json.dumps({
            "repair_candidates": len(candidates),
            "attempted_children": len(results),
            "successful_children": sum(row.ok for row in results),
            "parent_build_ids": sorted({row.parent_build_id for row in results}),
        }, indent=2) + "\n")
        return results
