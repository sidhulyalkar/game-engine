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
class SemanticRepairResult:
    provider: str
    parent_build_id: str
    parent_provider: str
    build_id: str
    ok: bool
    source_dir: str | None
    zip_path: str | None
    compressed_bytes: int | None
    byte_headroom: int | None
    repaired_blocker_codes: list[str]
    remaining_blocker_codes: list[str]
    remaining_major_codes: list[str]
    warnings: list[str]
    raw_response_path: str | None = None
    response_format: str | None = None
    source_falsification_path: str | None = None
    error: str | None = None


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value[:60] or "semantic-repairer"


def _finding_codes(report: dict[str, Any], severity: str) -> list[str]:
    return [
        str(row.get("code"))
        for row in report.get("findings") or []
        if str(row.get("severity")) == severity and row.get("code")
    ]


def load_semantic_repair_candidates(
    builds_root: Path,
    falsification_root: Path,
    max_parents: int = 1,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Select the cheapest plausible deterministic repairs, never clean builds."""
    evidence_path = falsification_root / "source-falsification.json"
    if not evidence_path.exists():
        raise FileNotFoundError(f"missing deterministic source evidence: {evidence_path}")
    evidence = json.loads(evidence_path.read_text())
    if not isinstance(evidence, list):
        raise ValueError("source-falsification.json must contain a list")

    builds = {str(row.get("build_id")): row for row in discover_builds(builds_root)}
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for report in evidence:
        if not isinstance(report, dict) or bool(report.get("qualified", False)):
            continue
        build_id = str(report.get("build_id", ""))
        build = builds.get(build_id)
        if not build:
            continue
        blockers = int(report.get("blockers", 0))
        if blockers <= 0:
            continue
        candidates.append((build, report))

    candidates.sort(key=lambda pair: (
        int(pair[1].get("blockers", 10**6)),
        int(pair[1].get("majors", 10**6)),
        -int(pair[0].get("byte_headroom") or 0),
        str(pair[0].get("build_id")),
    ))
    return candidates[: max(0, max_parents)]


def semantic_repair_prompt(
    brief: Brief,
    concept: Concept,
    game_spec: dict[str, Any],
    parent: dict[str, Any],
    source_report: dict[str, Any],
    html: str,
) -> tuple[str, str]:
    system = """You are a surgical gameplay engineer repairing one existing tiny web game from deterministic source-level falsification evidence. The concept and GameSpec are fixed. Make the smallest coherent source changes that remove the proven defects without redesigning the game. Return ONLY one complete standalone HTML document ending in </html>. No JSON, markdown, patch, explanation, or evaluator-specific fake state."""
    findings = source_report.get("findings") or []
    user = f"""COMPETITION BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nWINNING CONCEPT:\n{json.dumps(concept.to_dict(), indent=2)}\n\nAUTHORITATIVE GAMESPEC:\n{json.dumps(game_spec, indent=2)}\n\nPARENT BUILD METADATA:\n{json.dumps({k: v for k, v in parent.items() if k != 'resolved_source_dir'}, indent=2)}\n\nDETERMINISTIC SOURCE FINDINGS:\n{json.dumps(findings, indent=2)}\n\nCURRENT INDEX.HTML:\n{html}\n\nPerform exactly one bounded semantic repair. Hard rules:\n- remove every finding marked blocker using the smallest coherent source change\n- fix major findings too only when the same local edit safely resolves them\n- do not delete, rename, or cosmetically fake a required GameSpec mechanic/control to silence a finding\n- preserve the concept's defining interaction and all GameSpec actions marked required\n- preserve deterministic timing/seed requirements, bounded state, restart semantics, and truthful telemetry\n- telemetry must describe actual gameplay state, never a parallel evaluator-only state machine\n- if a finding says a declared cap is unused, enforce the cap rather than deleting the declaration or hiding the state\n- if a finding says input cannot reach its target, make the real player control reachable rather than removing the control\n- if a finding detects incorrect delta-time units, repair the physical units rather than changing thresholds to conceal the error\n- preserve working art/theme/pacing and add no unrelated features\n- remain below {brief.size_limit_bytes} compressed bytes with useful headroom\n- return the FULL repaired HTML document only\n"""
    return system, user


class SemanticRepairForge:
    """One bounded model repair after cheap deterministic source falsification."""

    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 2):
        self.clients = clients
        self.max_workers = max_workers

    def build(
        self,
        brief: Brief,
        concept: Concept,
        builds_root: Path,
        falsification_root: Path,
        output_dir: Path,
        max_parents: int = 1,
    ) -> list[SemanticRepairResult]:
        candidates = load_semantic_repair_candidates(
            builds_root,
            falsification_root,
            max_parents=max_parents,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_path = builds_root / "game-spec.json"
        if not spec_path.exists():
            raise FileNotFoundError(f"missing GameSpec: {spec_path}")
        game_spec = json.loads(spec_path.read_text())
        (output_dir / "game-spec.json").write_text(json.dumps(game_spec, indent=2) + "\n")

        if not candidates:
            (output_dir / "builds.json").write_text("[]\n")
            (output_dir / "semantic-repair-manifest.json").write_text(json.dumps({
                "repair_candidates": 0,
                "attempted_children": 0,
                "successful_children": 0,
            }, indent=2) + "\n")
            return []

        jobs = []
        for parent, source_report in candidates:
            html = (Path(parent["resolved_source_dir"]) / "index.html").read_text()
            system, prompt = semantic_repair_prompt(
                brief,
                concept,
                game_spec,
                parent,
                source_report,
                html,
            )
            for provider_spec, client in self.clients:
                jobs.append((provider_spec, client, parent, source_report, system, prompt))

        raw_dir = output_dir / "raw"
        meta_dir = output_dir / "meta"
        raw_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)
        results: list[SemanticRepairResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(_complete_with_provenance, client, system, prompt):
                    (provider_spec, client, parent, source_report)
                for provider_spec, client, parent, source_report, system, prompt in jobs
            }
            for future in as_completed(futures):
                provider_spec, client, parent, parent_report = futures[future]
                provider = getattr(provider_spec, "name", getattr(client, "name", "semantic-repairer"))
                parent_id = str(parent.get("build_id"))
                original_blockers = _finding_codes(parent_report, "blocker")
                raw_path: Path | None = None
                source_path: Path | None = None
                falsification_path: Path | None = None
                build_id = "failed"
                try:
                    response, finish_reason, usage = future.result()
                    raw_digest = hashlib.sha1(response.encode()).hexdigest()[:10]
                    raw_path = raw_dir / f"{_safe_name(provider)}-{parent_id}-{raw_digest}.txt"
                    raw_path.write_text(response)
                    repaired_html, response_format = _extract_html_response(response)
                    build_id = hashlib.sha1(
                        f"semantic-repair:{provider}:{parent_id}:{repaired_html}".encode()
                    ).hexdigest()[:10]
                    source_path = output_dir / f"{_safe_name(provider)}-{parent_id}-{build_id}"
                    source_path.mkdir(parents=True, exist_ok=True)
                    (source_path / "index.html").write_text(repaired_html)

                    repaired_report = analyze_source(repaired_html, game_spec)
                    remaining_blockers = _finding_codes(repaired_report, "blocker")
                    remaining_majors = _finding_codes(repaired_report, "major")
                    repaired_codes = sorted(set(original_blockers) - set(remaining_blockers))
                    falsification_path = meta_dir / f"{_safe_name(provider)}-{build_id}-source-falsification.json"
                    falsification_path.write_text(json.dumps(repaired_report, indent=2) + "\n")
                    (meta_dir / f"{_safe_name(provider)}-{build_id}.json").write_text(json.dumps({
                        "provider": provider,
                        "parent_build_id": parent_id,
                        "parent_source_findings": parent_report.get("findings", []),
                        "raw_response": str(raw_path),
                        "response_format": response_format,
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "repaired_source_falsification": repaired_report,
                    }, indent=2) + "\n")

                    if remaining_blockers:
                        results.append(SemanticRepairResult(
                            provider=provider,
                            parent_build_id=parent_id,
                            parent_provider=str(parent.get("provider", "unknown")),
                            build_id=build_id,
                            ok=False,
                            source_dir=str(source_path),
                            zip_path=None,
                            compressed_bytes=None,
                            byte_headroom=None,
                            repaired_blocker_codes=repaired_codes,
                            remaining_blocker_codes=remaining_blockers,
                            remaining_major_codes=remaining_majors,
                            warnings=[],
                            raw_response_path=str(raw_path),
                            response_format=response_format,
                            source_falsification_path=str(falsification_path),
                            error="SourceFalsificationError after semantic repair: " + ", ".join(remaining_blockers),
                        ))
                        continue

                    zip_path = output_dir / "dist" / f"{_safe_name(provider)}-{build_id}.zip"
                    package = package_game(source_path, zip_path, brief.size_limit_bytes)
                    results.append(SemanticRepairResult(
                        provider=provider,
                        parent_build_id=parent_id,
                        parent_provider=str(parent.get("provider", "unknown")),
                        build_id=build_id,
                        ok=package.ok,
                        source_dir=str(source_path),
                        zip_path=str(zip_path),
                        compressed_bytes=package.compressed_bytes,
                        byte_headroom=brief.size_limit_bytes - package.compressed_bytes,
                        repaired_blocker_codes=repaired_codes,
                        remaining_blocker_codes=[],
                        remaining_major_codes=remaining_majors,
                        warnings=list(package.warnings),
                        raw_response_path=str(raw_path),
                        response_format=response_format,
                        source_falsification_path=str(falsification_path),
                        error=None if package.ok else "compressed byte limit exceeded",
                    ))
                except Exception as exc:
                    results.append(SemanticRepairResult(
                        provider=provider,
                        parent_build_id=parent_id,
                        parent_provider=str(parent.get("provider", "unknown")),
                        build_id=build_id,
                        ok=False,
                        source_dir=str(source_path) if source_path else None,
                        zip_path=None,
                        compressed_bytes=None,
                        byte_headroom=None,
                        repaired_blocker_codes=[],
                        remaining_blocker_codes=original_blockers,
                        remaining_major_codes=[],
                        warnings=[],
                        raw_response_path=str(raw_path) if raw_path else None,
                        response_format=None,
                        source_falsification_path=str(falsification_path) if falsification_path else None,
                        error=f"{type(exc).__name__}: {exc}",
                    ))

        results.sort(key=lambda row: (
            not row.ok,
            len(row.remaining_blocker_codes),
            -(row.byte_headroom or -10**9),
            row.provider,
        ))
        (output_dir / "builds.json").write_text(json.dumps([asdict(row) for row in results], indent=2) + "\n")
        (output_dir / "semantic-repair-manifest.json").write_text(json.dumps({
            "repair_candidates": len(candidates),
            "attempted_children": len(results),
            "successful_children": sum(row.ok for row in results),
            "parent_build_ids": sorted({row.parent_build_id for row in results}),
            "all_original_blocker_codes": sorted({
                code for _, report in candidates for code in _finding_codes(report, "blocker")
            }),
        }, indent=2) + "\n")
        return results
