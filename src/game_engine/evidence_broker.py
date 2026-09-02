from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from .action_causality import ActionCausalityLab
from .restart_playtest import RestartEvidenceLab
from .visual_playtest import CanvasAwareGameplayEvidenceLab


@dataclass(slots=True)
class BehavioralDecision:
    build_id: str
    status: str
    eligible_for_llm_critics: bool
    action_causality: bool | None
    restart_integrity: bool | None
    independent_agency: bool | None
    telemetry_visual_contradiction: bool | None
    blockers: list[str]
    evidence_gaps: list[str]


def combine_behavioral_evidence(
    build_ids: Iterable[str],
    action_summary: dict[str, Any] | None,
    restart_summary: dict[str, Any] | None,
    visual_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine independent probes without averaging them into a fake quality score.

    Required-control causality, restart integrity, and independent player agency are
    veto-style development gates. Missing evidence is not candidate rejection: it is
    represented explicitly as `insufficient_evidence` and blocks expensive critics.
    """
    ids = sorted({str(value) for value in build_ids})
    action_pass = set((action_summary or {}).get("action_causality_pass_build_ids", []))
    action_fail = set((action_summary or {}).get("action_causality_fail_build_ids", []))
    restart_pass = set((restart_summary or {}).get("restart_pass_build_ids", []))
    restart_fail = set((restart_summary or {}).get("restart_fail_build_ids", []))
    agency_pass = set((visual_summary or {}).get("independently_observable_build_ids", []))
    agency_contradiction = set((visual_summary or {}).get("telemetry_visual_contradiction_build_ids", []))
    visual_tested = {
        str(row.get("build_id"))
        for row in (visual_summary or {}).get("builds", [])
        if isinstance(row, dict) and row.get("build_id") is not None
    }

    decisions: list[BehavioralDecision] = []
    for build_id in ids:
        blockers: list[str] = []
        gaps: list[str] = []

        if action_summary is None or (build_id not in action_pass and build_id not in action_fail):
            action: bool | None = None
            gaps.append("required-control causality evidence missing")
        else:
            action = build_id in action_pass
            if not action:
                blockers.append("one or more advertised required controls lack causal gameplay effect")

        if restart_summary is None or (build_id not in restart_pass and build_id not in restart_fail):
            restart: bool | None = None
            gaps.append("restart integrity evidence missing")
        else:
            restart = build_id in restart_pass
            if not restart:
                blockers.append("fresh-run restart contract failed")

        if visual_summary is None or build_id not in visual_tested:
            agency: bool | None = None
            contradiction: bool | None = None
            gaps.append("independent agency evidence missing")
        else:
            agency = build_id in agency_pass
            contradiction = build_id in agency_contradiction
            if not agency:
                blockers.append("active policy did not outperform matched null/idle behavior")
            if contradiction:
                blockers.append("telemetry claims mechanical response without independent visual support")

        if gaps:
            status = "insufficient_evidence"
        elif blockers:
            # These are development defects with coherent repair targets. Do not call
            # them terminal game-design rejection until a bounded repair has failed.
            status = "behavioral_repair"
        else:
            status = "behaviorally_qualified"

        decisions.append(BehavioralDecision(
            build_id=build_id,
            status=status,
            eligible_for_llm_critics=status == "behaviorally_qualified",
            action_causality=action,
            restart_integrity=restart,
            independent_agency=agency,
            telemetry_visual_contradiction=contradiction,
            blockers=sorted(set(blockers)),
            evidence_gaps=sorted(set(gaps)),
        ))

    return {
        "builds_tested": len(decisions),
        "behaviorally_qualified_build_ids": [row.build_id for row in decisions if row.status == "behaviorally_qualified"],
        "behavioral_repair_build_ids": [row.build_id for row in decisions if row.status == "behavioral_repair"],
        "insufficient_evidence_build_ids": [row.build_id for row in decisions if row.status == "insufficient_evidence"],
        "llm_critic_eligible_build_ids": [row.build_id for row in decisions if row.eligible_for_llm_critics],
        "decisions": [asdict(row) for row in decisions],
    }


class EvidenceBroker:
    """Run cheap behavioral falsification before subjective LLM criticism.

    Browser Reality is expected to have already qualified the build across the target
    browser matrix. These deeper causal probes intentionally use one reference browser
    by default to avoid tripling evidence cost before the metrics are calibrated.
    """

    def __init__(
        self,
        browsers: Iterable[str] = ("chromium",),
        sample_interval_ms: int = 160,
    ):
        self.browsers = tuple(browsers)
        self.sample_interval_ms = sample_interval_ms

    def run(
        self,
        builds_root: Path,
        output_dir: Path,
        reality_root: Path,
    ) -> dict[str, Any]:
        qualification_path = reality_root / "qualification.json"
        if not qualification_path.exists():
            raise ValueError(f"missing Browser Reality qualification: {qualification_path}")
        reality = json.loads(qualification_path.read_text())
        build_ids = [str(value) for value in reality.get("full_pass_build_ids", [])]
        if not build_ids:
            raise ValueError("no cross-browser-qualified builds are eligible for behavioral evidence")

        output_dir.mkdir(parents=True, exist_ok=True)
        errors: dict[str, str] = {}

        action_summary: dict[str, Any] | None = None
        try:
            action_summary = ActionCausalityLab(
                browsers=self.browsers,
                sample_interval_ms=self.sample_interval_ms,
            ).run(builds_root, output_dir / "action-causality", reality_root)
        except Exception as exc:
            errors["action_causality"] = f"{type(exc).__name__}: {exc}"

        restart_summary: dict[str, Any] | None = None
        try:
            restart_summary = RestartEvidenceLab(
                browsers=self.browsers,
                sample_interval_ms=self.sample_interval_ms,
            ).run(builds_root, output_dir / "restart", reality_root)
        except Exception as exc:
            errors["restart"] = f"{type(exc).__name__}: {exc}"

        visual_summary: dict[str, Any] | None = None
        try:
            visual_summary = CanvasAwareGameplayEvidenceLab(
                browsers=self.browsers,
                sample_interval_ms=self.sample_interval_ms,
            ).run(builds_root, output_dir / "agency", reality_root)
        except Exception as exc:
            errors["agency"] = f"{type(exc).__name__}: {exc}"

        result = combine_behavioral_evidence(
            build_ids,
            action_summary,
            restart_summary,
            visual_summary,
        )
        result["reference_browsers"] = list(self.browsers)
        result["probe_errors"] = errors
        result["all_probes_completed"] = not errors
        (output_dir / "evidence-broker.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
