from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .evidence_broker import EvidenceBroker, write_critic_reality_view
from .reality import BrowserRealityLab, discover_builds
from .source_falsification import SourceFalsificationLab


@dataclass(frozen=True, slots=True)
class BrowserStagePlan:
    reference_browser: str
    promotion_browsers: tuple[str, ...]
    final_browsers: tuple[str, ...]


@dataclass(slots=True)
class StagedEvidenceResult:
    status: str
    reference_browser: str
    promotion_browsers: list[str]
    semantic_qualified_build_ids: list[str]
    semantic_blocked_build_ids: list[str]
    semantic_view_root: str | None
    reference_browser_build_ids: list[str]
    behaviorally_qualified_build_ids: list[str]
    behavioral_repair_build_ids: list[str]
    insufficient_evidence_build_ids: list[str]
    behavioral_probe_errors: dict[str, str]
    promotion_attempted: bool
    cross_browser_build_ids: list[str]
    promotion_view_root: str | None
    final_reality_root: str | None
    critic_reality_root: str | None


def plan_browser_stages(browsers: Iterable[str]) -> BrowserStagePlan:
    """Choose one cheap reference engine, deferring the rest until gameplay qualifies."""
    ordered: list[str] = []
    for value in browsers:
        name = str(value).strip()
        if name and name not in ordered:
            ordered.append(name)
    if not ordered:
        raise ValueError("at least one browser is required")
    reference = "chromium" if "chromium" in ordered else ordered[0]
    promotion = tuple(name for name in ordered if name != reference)
    return BrowserStagePlan(
        reference_browser=reference,
        promotion_browsers=promotion,
        final_browsers=tuple(ordered),
    )


def write_build_view(
    source_root: Path,
    output_root: Path,
    allowed_build_ids: Iterable[str],
) -> dict:
    """Create a self-contained evaluator view containing only promoted builds.

    Copying the tiny game source makes the evidence artifact portable after Actions
    extraction and prevents a later evaluator from accidentally rediscovering a
    sibling that failed an earlier gate.
    """
    allowed = sorted({str(value) for value in allowed_build_ids})
    if not allowed:
        raise ValueError("promotion build view requires at least one allowed build")

    discovered = {str(row["build_id"]): row for row in discover_builds(source_root)}
    missing = sorted(set(allowed) - set(discovered))
    if missing:
        raise ValueError(f"promotion build ids not present in source field: {missing}")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    sources_root = output_root / "sources"
    sources_root.mkdir()

    rows = []
    for build_id in allowed:
        source = discovered[build_id]
        src_dir = Path(source["resolved_source_dir"])
        dest_dir = sources_root / build_id
        shutil.copytree(src_dir, dest_dir)
        row = {
            key: value
            for key, value in source.items()
            if key != "resolved_source_dir"
        }
        row["source_dir"] = str(dest_dir)
        rows.append(row)

    spec_path = source_root / "game-spec.json"
    if not spec_path.exists():
        raise ValueError(f"missing GameSpec for promotion view: {spec_path}")
    (output_root / "game-spec.json").write_text(spec_path.read_text())
    (output_root / "builds.json").write_text(json.dumps(rows, indent=2) + "\n")

    manifest = {
        "source_root": str(source_root),
        "allowed_build_ids": allowed,
        "build_count": len(rows),
        "self_contained_sources": True,
    }
    (output_root / "promotion-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


class StagedEvidenceFunnel:
    """Spend evidence in ascending order of cost and subjectivity.

    This coordinator is deliberately lineage-local: callers can run it on original
    builder output or on a repair field. It does not choose concepts or repair games.
    It proves one implementation lineage through:

      source semantics -> reference browser -> M4 behavior -> promoted build view
      -> full browser field -> critic-ready reality.

    A deterministic source blocker therefore pays zero browser-install cost, while a
    behavioral failure pays only the reference-engine cost.
    """

    def __init__(
        self,
        *,
        install_browsers: bool = False,
        installer: Callable[[tuple[str, ...]], None] | None = None,
        source_falsification_factory=SourceFalsificationLab,
        reality_factory=BrowserRealityLab,
        broker_factory=EvidenceBroker,
        timeout_ms: int = 12_000,
        sample_interval_ms: int = 160,
    ):
        self.install_browsers = install_browsers
        self.installer = installer
        self.source_falsification_factory = source_falsification_factory
        self.reality_factory = reality_factory
        self.broker_factory = broker_factory
        self.timeout_ms = timeout_ms
        self.sample_interval_ms = sample_interval_ms
        if self.install_browsers and self.installer is None:
            raise ValueError("install_browsers=True requires an installer callback")

    def _install(self, browsers: tuple[str, ...]) -> None:
        if self.install_browsers and browsers:
            assert self.installer is not None
            self.installer(browsers)

    def run(
        self,
        builds_root: Path,
        output_dir: Path,
        browsers: Iterable[str],
    ) -> dict:
        plan = plan_browser_stages(browsers)
        output_dir.mkdir(parents=True, exist_ok=True)

        semantic_root = output_dir / "semantic-falsification"
        semantic = self.source_falsification_factory().run(
            builds_root,
            semantic_root,
        )
        semantic_qualified = [
            str(value) for value in semantic.get("full_pass_build_ids", [])
        ]
        semantic_blocked = [
            str(value) for value in semantic.get("blocked_build_ids", [])
        ]
        if not semantic_qualified:
            result = StagedEvidenceResult(
                status="semantic_falsification_failed",
                reference_browser=plan.reference_browser,
                promotion_browsers=list(plan.promotion_browsers),
                semantic_qualified_build_ids=[],
                semantic_blocked_build_ids=semantic_blocked,
                semantic_view_root=None,
                reference_browser_build_ids=[],
                behaviorally_qualified_build_ids=[],
                behavioral_repair_build_ids=[],
                insufficient_evidence_build_ids=[],
                behavioral_probe_errors={},
                promotion_attempted=False,
                cross_browser_build_ids=[],
                promotion_view_root=None,
                final_reality_root=None,
                critic_reality_root=None,
            )
            return self._write_result(output_dir, result)

        semantic_view = output_dir / "semantic-view"
        write_build_view(builds_root, semantic_view, semantic_qualified)

        self._install((plan.reference_browser,))
        reference_root = output_dir / "reference-reality"
        reference = self.reality_factory(
            browsers=(plan.reference_browser,),
            timeout_ms=self.timeout_ms,
        ).run(semantic_view, reference_root)
        reference_ids = [str(value) for value in reference.get("full_pass_build_ids", [])]
        if not reference_ids:
            result = StagedEvidenceResult(
                status="reference_browser_failed",
                reference_browser=plan.reference_browser,
                promotion_browsers=list(plan.promotion_browsers),
                semantic_qualified_build_ids=semantic_qualified,
                semantic_blocked_build_ids=semantic_blocked,
                semantic_view_root=str(semantic_view),
                reference_browser_build_ids=[],
                behaviorally_qualified_build_ids=[],
                behavioral_repair_build_ids=[],
                insufficient_evidence_build_ids=[],
                behavioral_probe_errors={},
                promotion_attempted=False,
                cross_browser_build_ids=[],
                promotion_view_root=None,
                final_reality_root=None,
                critic_reality_root=None,
            )
            return self._write_result(output_dir, result)

        behavior_root = output_dir / "behavior"
        behavior = self.broker_factory(
            browsers=(plan.reference_browser,),
            sample_interval_ms=self.sample_interval_ms,
        ).run(semantic_view, behavior_root, reference_root)
        qualified = [str(value) for value in behavior.get("behaviorally_qualified_build_ids", [])]
        repair = [str(value) for value in behavior.get("behavioral_repair_build_ids", [])]
        insufficient = [str(value) for value in behavior.get("insufficient_evidence_build_ids", [])]
        probe_errors = {
            str(key): str(value)
            for key, value in dict(behavior.get("probe_errors", {})).items()
        }
        if not qualified:
            if insufficient or probe_errors:
                status = "behavioral_evidence_incomplete"
            elif repair:
                status = "behavioral_repair_required"
            else:
                status = "behavioral_failure"
            result = StagedEvidenceResult(
                status=status,
                reference_browser=plan.reference_browser,
                promotion_browsers=list(plan.promotion_browsers),
                semantic_qualified_build_ids=semantic_qualified,
                semantic_blocked_build_ids=semantic_blocked,
                semantic_view_root=str(semantic_view),
                reference_browser_build_ids=reference_ids,
                behaviorally_qualified_build_ids=[],
                behavioral_repair_build_ids=repair,
                insufficient_evidence_build_ids=insufficient,
                behavioral_probe_errors=probe_errors,
                promotion_attempted=False,
                cross_browser_build_ids=[],
                promotion_view_root=None,
                final_reality_root=None,
                critic_reality_root=None,
            )
            return self._write_result(output_dir, result)

        # A one-browser tournament needs no compatibility promotion. Reuse the
        # reference evidence rather than paying for the same browser twice.
        if not plan.promotion_browsers:
            final_ids = sorted(set(reference_ids) & set(qualified))
            critic_root = output_dir / "critic-reality"
            write_critic_reality_view(reference_root, critic_root, final_ids)
            result = StagedEvidenceResult(
                status="qualified",
                reference_browser=plan.reference_browser,
                promotion_browsers=[],
                semantic_qualified_build_ids=semantic_qualified,
                semantic_blocked_build_ids=semantic_blocked,
                semantic_view_root=str(semantic_view),
                reference_browser_build_ids=reference_ids,
                behaviorally_qualified_build_ids=qualified,
                behavioral_repair_build_ids=repair,
                insufficient_evidence_build_ids=insufficient,
                behavioral_probe_errors=probe_errors,
                promotion_attempted=False,
                cross_browser_build_ids=final_ids,
                promotion_view_root=None,
                final_reality_root=str(reference_root),
                critic_reality_root=str(critic_root),
            )
            return self._write_result(output_dir, result)

        promotion_view = output_dir / "promotion-view"
        write_build_view(semantic_view, promotion_view, qualified)

        # Firefox/WebKit or other compatibility engines are installed only here,
        # after the candidate has proved causal controls/restart/agency in the
        # reference engine. A behavioral failure therefore never pays this cost.
        self._install(plan.promotion_browsers)
        final_reality_root = output_dir / "final-reality"
        final_reality = self.reality_factory(
            browsers=plan.final_browsers,
            timeout_ms=self.timeout_ms,
        ).run(promotion_view, final_reality_root)
        cross_browser = [str(value) for value in final_reality.get("full_pass_build_ids", [])]
        if not cross_browser:
            result = StagedEvidenceResult(
                status="cross_browser_failed",
                reference_browser=plan.reference_browser,
                promotion_browsers=list(plan.promotion_browsers),
                semantic_qualified_build_ids=semantic_qualified,
                semantic_blocked_build_ids=semantic_blocked,
                semantic_view_root=str(semantic_view),
                reference_browser_build_ids=reference_ids,
                behaviorally_qualified_build_ids=qualified,
                behavioral_repair_build_ids=repair,
                insufficient_evidence_build_ids=insufficient,
                behavioral_probe_errors=probe_errors,
                promotion_attempted=True,
                cross_browser_build_ids=[],
                promotion_view_root=str(promotion_view),
                final_reality_root=str(final_reality_root),
                critic_reality_root=None,
            )
            return self._write_result(output_dir, result)

        # Behavior was proved on the reference browser; final compatibility can only
        # narrow that set. Publish one final reality envelope for expensive critics.
        final_ids = sorted(set(cross_browser) & set(qualified))
        critic_root = output_dir / "critic-reality"
        write_critic_reality_view(final_reality_root, critic_root, final_ids)
        result = StagedEvidenceResult(
            status="qualified",
            reference_browser=plan.reference_browser,
            promotion_browsers=list(plan.promotion_browsers),
            semantic_qualified_build_ids=semantic_qualified,
            semantic_blocked_build_ids=semantic_blocked,
            semantic_view_root=str(semantic_view),
            reference_browser_build_ids=reference_ids,
            behaviorally_qualified_build_ids=qualified,
            behavioral_repair_build_ids=repair,
            insufficient_evidence_build_ids=insufficient,
            behavioral_probe_errors=probe_errors,
            promotion_attempted=True,
            cross_browser_build_ids=final_ids,
            promotion_view_root=str(promotion_view),
            final_reality_root=str(final_reality_root),
            critic_reality_root=str(critic_root),
        )
        return self._write_result(output_dir, result)

    @staticmethod
    def _write_result(output_dir: Path, result: StagedEvidenceResult) -> dict:
        payload = asdict(result)
        (output_dir / "staged-evidence.json").write_text(json.dumps(payload, indent=2) + "\n")
        return payload
