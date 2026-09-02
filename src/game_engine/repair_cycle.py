from __future__ import annotations

import json
from pathlib import Path

from .config import build_clients, load_provider_specs
from .repair import RepairForge
from .reality import BrowserRealityLab
from .schema import Brief, Concept
from .source_audit import SourceGameplayLab


_STATUS_RANK = {"reject": 0, "repair": 1, "advance": 2}


def evidence_improved(parent: dict, child: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    parent_status = str(parent.get("status", "reject"))
    child_status = str(child.get("status", "reject"))
    parent_rank = _STATUS_RANK.get(parent_status, 0)
    child_rank = _STATUS_RANK.get(child_status, 0)
    parent_overall = float(parent.get("overall", 0.0))
    child_overall = float(child.get("overall", 0.0))
    parent_blockers = int(parent.get("blockers", 0))
    child_blockers = int(child.get("blockers", 0))

    if child_blockers > parent_blockers:
        return False, ["child introduced additional blockers"]
    if child_rank < parent_rank:
        return False, ["child verdict regressed"]
    if child_rank > parent_rank:
        reasons.append(f"verdict improved {parent_status}->{child_status}")
    if child_overall >= parent_overall + 0.25:
        reasons.append(f"audit score improved {parent_overall:.3f}->{child_overall:.3f}")
    if child_blockers < parent_blockers and child_overall >= parent_overall - 0.1:
        reasons.append(f"blockers reduced {parent_blockers}->{child_blockers}")
    return bool(reasons), reasons


def _audit_map(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {str(row.get("build_id")): row for row in json.loads(path.read_text())}


def run_repair_cycle(
    winner_path: Path,
    builds_root: Path,
    parent_audits_root: Path,
    repair_config: Path,
    audit_config: Path,
    output_dir: Path,
    browsers: list[str],
    max_parents: int = 1,
    workers: int = 4,
    timeout_ms: int = 12_000,
) -> dict:
    payload = json.loads(winner_path.read_text())
    brief = Brief.from_dict(payload["brief"])
    concept = Concept.from_dict(payload["concept"])
    output_dir.mkdir(parents=True, exist_ok=True)

    repair_specs = load_provider_specs(repair_config)
    repair_clients = build_clients(repair_specs)
    repair_root = output_dir / "repairs"
    repairs = RepairForge(repair_clients, max_workers=workers).build(
        brief,
        concept,
        builds_root,
        parent_audits_root,
        repair_root,
        max_parents=max_parents,
    )
    successful_repairs = [row for row in repairs if row.ok]
    candidate_count = len({row.parent_build_id for row in repairs})
    if not repairs:
        summary = {
            "status": "no_repair_candidates",
            "repair_candidates": 0,
            "successful_children": 0,
            "cross_browser_children": 0,
            "critic_complete_children": 0,
            "evidence_improving_children": [],
            "comparisons": [],
        }
        (output_dir / "cycle-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary
    if not successful_repairs:
        summary = {
            "status": "repair_generation_failed",
            "repair_candidates": candidate_count,
            "successful_children": 0,
            "cross_browser_children": 0,
            "critic_complete_children": 0,
            "evidence_improving_children": [],
            "comparisons": [],
        }
        (output_dir / "cycle-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    reality_root = output_dir / "reality"
    reality = BrowserRealityLab(browsers=browsers, timeout_ms=timeout_ms).run(repair_root, reality_root)
    full_pass = set(reality.get("full_pass_build_ids", []))
    if not full_pass:
        summary = {
            "status": "children_failed_browser",
            "repair_candidates": candidate_count,
            "successful_children": len(successful_repairs),
            "cross_browser_children": 0,
            "critic_complete_children": 0,
            "evidence_improving_children": [],
            "comparisons": [],
        }
        (output_dir / "cycle-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    audit_specs = load_provider_specs(audit_config)
    audit_clients = build_clients(audit_specs)
    child_audit_root = output_dir / "audit"
    SourceGameplayLab(audit_clients, max_workers=workers).run(
        brief,
        concept,
        repair_root,
        child_audit_root,
        reality_root,
    )

    parent_audits = _audit_map(parent_audits_root / "audits.json")
    child_audits = _audit_map(child_audit_root / "audits.json")
    repair_map = {row.build_id: row for row in successful_repairs}
    comparisons = []
    improving = []
    critic_complete = 0
    for child_id in sorted(full_pass):
        repair = repair_map.get(child_id)
        child = child_audits.get(child_id)
        if repair is None or child is None:
            continue
        parent = parent_audits.get(repair.parent_build_id)
        if parent is None:
            continue
        critics = int(child.get("critic_count", 0))
        complete = critics >= 2
        if complete:
            critic_complete += 1
        improved, reasons = evidence_improved(parent, child) if complete else (False, ["fewer than two successful child critics"])
        comparison = {
            "parent_build_id": repair.parent_build_id,
            "child_build_id": child_id,
            "repair_provider": repair.provider,
            "browser_passed": True,
            "critic_count": critics,
            "parent_status": parent.get("status"),
            "child_status": child.get("status"),
            "parent_overall": parent.get("overall"),
            "child_overall": child.get("overall"),
            "parent_blockers": parent.get("blockers"),
            "child_blockers": child.get("blockers"),
            "evidence_improved": improved,
            "improvement_reasons": reasons,
        }
        comparisons.append(comparison)
        if improved:
            improving.append(child_id)

    if critic_complete == 0:
        status = "child_audit_failed"
    else:
        status = "complete"
    summary = {
        "status": status,
        "repair_candidates": candidate_count,
        "successful_children": len(successful_repairs),
        "cross_browser_children": len(full_pass),
        "critic_complete_children": critic_complete,
        "evidence_improving_children": improving,
        "comparisons": comparisons,
    }
    (output_dir / "cycle-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
