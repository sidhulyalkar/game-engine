from __future__ import annotations

import json
from pathlib import Path

from .config import build_clients, load_provider_specs
from .evidence_broker import EvidenceBroker
from .evidence_funnel import StagedEvidenceFunnel
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


def _structured_actions(builds_root: Path) -> bool:
    path = builds_root / "game-spec.json"
    if not path.exists():
        return False
    payload = json.loads(path.read_text())
    actions = payload.get("actions")
    return isinstance(actions, list) and bool(actions)


def _behavioral_child_gate(
    repair_root: Path,
    reality_root: Path,
    output_dir: Path,
) -> dict:
    """Legacy compatibility gate for repair artifacts without structured actions.

    Modern structured children use `_staged_child_gate` instead. Keeping the old
    branch explicit prevents historical artifacts from being silently relabeled as
    authoritative GameSpec-action evidence.
    """
    qualification = reality_root / "qualification.json"
    browser_ids = []
    if qualification.exists():
        browser_ids = [str(value) for value in json.loads(qualification.read_text()).get("full_pass_build_ids", [])]

    if not _structured_actions(repair_root):
        return {
            "applied": False,
            "policy": "legacy-browser-only",
            "reason": "legacy GameSpec has no structured actions; authoritative M4 not claimed",
            "qualified_build_ids": browser_ids,
            "repair_build_ids": [],
            "insufficient_evidence_build_ids": [],
            "probe_errors": {},
            "critic_reality_root": str(reality_root),
        }

    behavior_root = output_dir / "behavior"
    result = EvidenceBroker(browsers=("chromium",), sample_interval_ms=160).run(
        repair_root,
        behavior_root,
        reality_root,
    )
    return {
        "applied": True,
        "policy": "structured-actions-after-browser-legacy-path",
        "reason": "structured GameSpec.actions require causal behavioral evidence",
        "qualified_build_ids": [str(value) for value in result.get("behaviorally_qualified_build_ids", [])],
        "repair_build_ids": [str(value) for value in result.get("behavioral_repair_build_ids", [])],
        "insufficient_evidence_build_ids": [str(value) for value in result.get("insufficient_evidence_build_ids", [])],
        "probe_errors": dict(result.get("probe_errors", {})),
        "critic_reality_root": str(behavior_root / "critic-reality"),
    }


def _staged_child_gate(
    repair_root: Path,
    output_dir: Path,
    browsers: list[str],
    timeout_ms: int,
    funnel_factory=StagedEvidenceFunnel,
) -> dict:
    """Apply the same cheap-to-expensive evidence ladder used by first-generation builds."""
    root = output_dir / "staged-evidence"
    result = funnel_factory(
        install_browsers=False,
        timeout_ms=timeout_ms,
        sample_interval_ms=160,
    ).run(repair_root, root, browsers)
    return {
        "applied": True,
        "policy": "structured-staged-evidence",
        "status": str(result.get("status", "unknown")),
        "semantic_qualified_build_ids": [str(v) for v in result.get("semantic_qualified_build_ids", [])],
        "semantic_blocked_build_ids": [str(v) for v in result.get("semantic_blocked_build_ids", [])],
        "reference_browser_build_ids": [str(v) for v in result.get("reference_browser_build_ids", [])],
        "behaviorally_qualified_build_ids": [str(v) for v in result.get("behaviorally_qualified_build_ids", [])],
        "repair_build_ids": [str(v) for v in result.get("behavioral_repair_build_ids", [])],
        "insufficient_evidence_build_ids": [str(v) for v in result.get("insufficient_evidence_build_ids", [])],
        "probe_errors": dict(result.get("behavioral_probe_errors", {})),
        "qualified_build_ids": [str(v) for v in result.get("cross_browser_build_ids", [])],
        "critic_reality_root": result.get("critic_reality_root"),
        "staged_evidence_root": str(root),
    }


def _staged_failure_status(gate: dict) -> str:
    status = str(gate.get("status", "unknown"))
    if status == "semantic_falsification_failed":
        return "children_failed_semantics"
    if status == "reference_browser_failed":
        return "children_failed_reference_browser"
    if status == "behavioral_evidence_incomplete":
        return "child_behavior_evidence_incomplete"
    if status in {"behavioral_repair_required", "behavioral_failure"}:
        return "children_failed_behavior"
    if status == "cross_browser_failed":
        return "children_failed_browser"
    return "child_evidence_failed"


def _write_summary(output_dir: Path, summary: dict) -> dict:
    (output_dir / "cycle-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


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
        return _write_summary(output_dir, {
            "status": "no_repair_candidates",
            "repair_candidates": 0,
            "successful_children": 0,
            "cross_browser_children": 0,
            "behaviorally_qualified_children": 0,
            "critic_complete_children": 0,
            "evidence_improving_children": [],
            "comparisons": [],
        })
    if not successful_repairs:
        return _write_summary(output_dir, {
            "status": "repair_generation_failed",
            "repair_candidates": candidate_count,
            "successful_children": 0,
            "cross_browser_children": 0,
            "behaviorally_qualified_children": 0,
            "critic_complete_children": 0,
            "evidence_improving_children": [],
            "comparisons": [],
        })

    structured = _structured_actions(repair_root)
    if structured:
        # Modern children inherit the exact same evidence constitution as their
        # parents: static source semantics before any browser, then reference-browser
        # M4, then the remaining compatibility browsers. Critics do not exist yet.
        child_gate = _staged_child_gate(
            repair_root,
            output_dir,
            browsers,
            timeout_ms,
        )
        full_pass = set(child_gate["qualified_build_ids"])
        behavior_pass = set(child_gate["behaviorally_qualified_build_ids"])
        if not full_pass:
            return _write_summary(output_dir, {
                "status": _staged_failure_status(child_gate),
                "repair_candidates": candidate_count,
                "successful_children": len(successful_repairs),
                "cross_browser_children": 0,
                "behaviorally_qualified_children": len(behavior_pass),
                "behavioral_gate": child_gate,
                "critic_complete_children": 0,
                "evidence_improving_children": [],
                "comparisons": [],
            })
        critic_reality_root = Path(str(child_gate["critic_reality_root"]))
    else:
        # Historical artifacts keep their old browser-only contract and are labeled
        # as such. They remain analyzable but never masquerade as strict M4 evidence.
        reality_root = output_dir / "reality"
        reality = BrowserRealityLab(browsers=browsers, timeout_ms=timeout_ms).run(repair_root, reality_root)
        full_pass = set(str(value) for value in reality.get("full_pass_build_ids", []))
        if not full_pass:
            return _write_summary(output_dir, {
                "status": "children_failed_browser",
                "repair_candidates": candidate_count,
                "successful_children": len(successful_repairs),
                "cross_browser_children": 0,
                "behaviorally_qualified_children": 0,
                "critic_complete_children": 0,
                "evidence_improving_children": [],
                "comparisons": [],
            })
        child_gate = _behavioral_child_gate(repair_root, reality_root, output_dir)
        behavior_pass = set(child_gate["qualified_build_ids"])
        critic_reality_root = Path(child_gate["critic_reality_root"])

    # Critic clients are deliberately constructed only after final staged/browser
    # qualification. Broken controls, static semantics, or incompatible children
    # therefore spend zero child-critic tokens.
    audit_specs = load_provider_specs(audit_config)
    audit_clients = build_clients(audit_specs)
    child_audit_root = output_dir / "audit"
    SourceGameplayLab(audit_clients, max_workers=workers).run(
        brief,
        concept,
        repair_root,
        child_audit_root,
        critic_reality_root,
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
        improved, reasons = evidence_improved(parent, child) if complete else (
            False,
            ["fewer than two successful child critics"],
        )
        comparison = {
            "parent_build_id": repair.parent_build_id,
            "child_build_id": child_id,
            "repair_provider": repair.provider,
            "browser_passed": child_id in full_pass,
            "behaviorally_qualified": child_id in behavior_pass,
            "behavioral_policy": child_gate.get("policy"),
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

    status = "child_audit_failed" if critic_complete == 0 else "complete"
    return _write_summary(output_dir, {
        "status": status,
        "repair_candidates": candidate_count,
        "successful_children": len(successful_repairs),
        "cross_browser_children": len(full_pass),
        "behaviorally_qualified_children": len(behavior_pass),
        "behavioral_gate": child_gate,
        "critic_complete_children": critic_complete,
        "evidence_improving_children": improving,
        "comparisons": comparisons,
    })
