from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .packaging import package_game
from .providers.base import LLMClient
from .reality import discover_builds
from .schema import Brief, Concept
from .swarm import _extract_json


@dataclass(slots=True)
class RepairResult:
    provider: str
    parent_build_id: str
    parent_provider: str
    parent_overall: float
    parent_blockers: int
    build_id: str
    ok: bool
    source_dir: str | None
    zip_path: str | None
    compressed_bytes: int | None
    byte_headroom: int | None
    warnings: list[str]
    error: str | None = None


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value[:60] or "repairer"


def repair_prompt(brief: Brief, concept: Concept, parent: dict, audit: dict, html: str) -> tuple[str, str]:
    system = """You are a surgical senior game engineer repairing a tiny web-game prototype after independent gameplay audits. Preserve the parent's strongest working interaction. Fix confirmed defects with the smallest coherent change. Do not redesign the game just to make coding easier. Return strict JSON only."""
    schema = {
        "index_html": "complete repaired standalone HTML document as a string",
        "repair_notes": ["specific finding -> concrete fix"],
    }
    user = f"""COMPETITION BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nWINNING CONCEPT CONTRACT:\n{json.dumps(concept.to_dict(), indent=2)}\n\nPARENT BUILD:\n{json.dumps({k: v for k, v in parent.items() if k != 'resolved_source_dir'}, indent=2)}\n\nINDEPENDENT AUDIT AGGREGATE:\n{json.dumps(audit, indent=2)}\n\nPARENT INDEX.HTML:\n{html}\n\nCreate a repaired child. Requirements:\n- fix every credible blocker and major finding before polishing minors\n- preserve the intended core interaction and all parent behavior that is already correct\n- verify numeric units and delta-time multiplication\n- verify object/property comparisons, entity cleanup, bounded arrays/state, collision logic, score progression, game-over, and restart\n- controls shown to the player must match the implemented control geometry\n- restore concept fidelity when the implementation substituted a simpler generic mechanic\n- preserve or improve visual identity and feedback; do not replace recognizable themed subjects with placeholder circles\n- no remote assets, scripts, fonts, or network dependency\n- remain standalone and target substantial headroom under {brief.size_limit_bytes} compressed bytes\n- do not minify into unreadable code during repair; correctness comes first\n\nReturn exactly this JSON shape, no markdown fences:\n{json.dumps(schema, indent=2)}"""
    return system, user


def load_repair_candidates(builds_root: Path, audits_root: Path, max_parents: int = 1) -> list[tuple[dict, dict]]:
    builds = {row["build_id"]: row for row in discover_builds(builds_root)}
    audit_path = audits_root / "audits.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"missing gameplay audits: {audit_path}")
    audits = json.loads(audit_path.read_text())
    candidates = []
    for audit in audits:
        if audit.get("status") != "repair":
            continue
        build = builds.get(audit.get("build_id"))
        if not build:
            continue
        candidates.append((build, audit))
    candidates.sort(key=lambda row: (-float(row[1].get("overall", 0.0)), int(row[1].get("blockers", 0))))
    return candidates[:max(0, max_parents)]


class RepairForge:
    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 4):
        self.clients = clients
        self.max_workers = max_workers

    def build(
        self,
        brief: Brief,
        concept: Concept,
        builds_root: Path,
        audits_root: Path,
        output_dir: Path,
        max_parents: int = 1,
    ) -> list[RepairResult]:
        candidates = load_repair_candidates(builds_root, audits_root, max_parents=max_parents)
        output_dir.mkdir(parents=True, exist_ok=True)
        if not candidates:
            (output_dir / "repairs.json").write_text("[]\n")
            (output_dir / "repair-manifest.json").write_text(json.dumps({"repair_candidates": 0, "successful_children": 0}, indent=2) + "\n")
            return []

        jobs = []
        for parent, audit in candidates:
            html = (Path(parent["resolved_source_dir"]) / "index.html").read_text()
            system, prompt = repair_prompt(brief, concept, parent, audit, html)
            for spec, client in self.clients:
                jobs.append((spec, client, parent, audit, system, prompt))

        results: list[RepairResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {
                pool.submit(client.complete, system, prompt): (spec, client, parent, audit)
                for spec, client, parent, audit, system, prompt in jobs
            }
            for future in as_completed(future_map):
                spec, client, parent, audit = future_map[future]
                provider = getattr(spec, "name", getattr(client, "name", "repairer"))
                try:
                    payload = _extract_json(future.result())
                    html = payload.get("index_html")
                    if not isinstance(html, str) or "<html" not in html.lower():
                        raise ValueError("repair provider did not return a complete index_html document")
                    build_id = hashlib.sha1(
                        f"repair:{provider}:{parent['build_id']}:{html}".encode()
                    ).hexdigest()[:10]
                    build_dir = output_dir / f"{_safe_name(provider)}-{parent['build_id']}-{build_id}"
                    build_dir.mkdir(parents=True, exist_ok=True)
                    (build_dir / "index.html").write_text(html)
                    (build_dir / "repair-notes.json").write_text(json.dumps({
                        "provider": provider,
                        "parent_build_id": parent["build_id"],
                        "parent_provider": parent.get("provider"),
                        "parent_audit_overall": audit.get("overall"),
                        "parent_blockers": audit.get("blockers"),
                        "repair_notes": payload.get("repair_notes", []),
                    }, indent=2) + "\n")
                    zip_path = output_dir / "dist" / f"{_safe_name(provider)}-{build_id}.zip"
                    report = package_game(build_dir, zip_path, brief.size_limit_bytes)
                    warnings = list(report.warnings)
                    if "<canvas" not in html.lower():
                        warnings.append("No canvas element detected; verify rendering strategy intentionally.")
                    results.append(RepairResult(
                        provider=provider,
                        parent_build_id=parent["build_id"],
                        parent_provider=parent.get("provider", "unknown"),
                        parent_overall=float(audit.get("overall", 0.0)),
                        parent_blockers=int(audit.get("blockers", 0)),
                        build_id=build_id,
                        ok=report.ok,
                        source_dir=str(build_dir),
                        zip_path=str(zip_path),
                        compressed_bytes=report.compressed_bytes,
                        byte_headroom=brief.size_limit_bytes - report.compressed_bytes,
                        warnings=warnings,
                    ))
                except Exception as exc:
                    results.append(RepairResult(
                        provider=provider,
                        parent_build_id=parent["build_id"],
                        parent_provider=parent.get("provider", "unknown"),
                        parent_overall=float(audit.get("overall", 0.0)),
                        parent_blockers=int(audit.get("blockers", 0)),
                        build_id="failed",
                        ok=False,
                        source_dir=None,
                        zip_path=None,
                        compressed_bytes=None,
                        byte_headroom=None,
                        warnings=[],
                        error=f"{type(exc).__name__}: {exc}",
                    ))

        results.sort(key=lambda row: (not row.ok, row.parent_build_id, -(row.byte_headroom or -10**9), row.provider))
        (output_dir / "repairs.json").write_text(json.dumps([asdict(row) for row in results], indent=2) + "\n")
        (output_dir / "builds.json").write_text(json.dumps([asdict(row) for row in results], indent=2) + "\n")
        manifest = {
            "repair_candidates": len(candidates),
            "attempted_children": len(results),
            "successful_children": sum(row.ok for row in results),
            "parent_build_ids": sorted({row.parent_build_id for row in results}),
        }
        (output_dir / "repair-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return results
