from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .action_policy import ActionPlanError, InputProgramStep, compile_input_program, execute_input_program
from .playtest import _finite_number, _load_game_spec, _qualified_ids
from .reality import discover_builds, serve_directory
from .structured_playtest import _POINTER_SURFACE_JS
from .visual_playtest import CanvasAwareGameplayEvidenceLab


_SEMANTIC_FIELDS = (
    "state",
    "alive",
    "game_over",
    "score",
    "progress",
    "entity_count",
    "progression_transitions",
    "restart_count",
)


@dataclass(slots=True)
class ActionTrial:
    build_id: str
    provider: str
    browser: str
    action_id: str
    kind: str
    binding: str | None
    direction: str | None
    required: bool
    ok: bool
    accepted: bool
    meaningful_state_change: bool
    independent_visual_change: bool
    action_count_delta: float | None
    score_delta: float | None
    progress_delta: float | None
    core_mechanic_delta: float | None
    progression_delta: float | None
    response_ms: float
    before_state_hash: str | None
    after_state_hash: str | None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    matched_control: bool = False
    control_meaningful_state_change: bool = False
    control_visual_change: bool = False


@dataclass(slots=True)
class ActionSummary:
    action_id: str
    required: bool
    trials: int
    passed_trials: int
    failed_trials: int
    no_op_fraction: float
    ok: bool


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float | None:
    a, b = before.get(key), after.get(key)
    if not _finite_number(a) or not _finite_number(b):
        return None
    return round(float(b) - float(a), 6)


def _event_count(events: list[dict[str, Any]], event_type: str) -> int:
    return sum(str(row.get("type")) == event_type for row in events)


def _transition_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return any(before.get(key) != after.get(key) for key in _SEMANTIC_FIELDS)


def _causal_semantic_change(
    before: dict[str, Any],
    after: dict[str, Any],
    control_before: dict[str, Any] | None,
    control_after: dict[str, Any] | None,
) -> bool:
    """Return true only for semantic effects not explained by a matched idle trial."""
    if control_before is None or control_after is None:
        return _transition_changed(before, after)

    for key in _SEMANTIC_FIELDS:
        a0, a1 = before.get(key), after.get(key)
        c0, c1 = control_before.get(key), control_after.get(key)
        numeric = (
            not isinstance(a0, bool)
            and not isinstance(a1, bool)
            and not isinstance(c0, bool)
            and not isinstance(c1, bool)
            and _finite_number(a0)
            and _finite_number(a1)
            and _finite_number(c0)
            and _finite_number(c1)
        )
        if numeric:
            active_delta = float(a1) - float(a0)
            control_delta = float(c1) - float(c0)
            if abs(active_delta - control_delta) > 1e-6:
                return True
            continue
        active_transition = (a0, a1)
        control_transition = (c0, c1)
        if a0 != a1 and active_transition != control_transition:
            return True
    return False


def split_action_trials(program: list[InputProgramStep]) -> list[list[InputProgramStep]]:
    """Split one deterministic action program at explicit sample boundaries.

    Each returned segment is independently executable from a fresh page and ends at
    exactly one advertised binding/direction boundary. This prevents one working
    control from contaminating evidence for a later broken control.
    """
    trials: list[list[InputProgramStep]] = []
    current: list[InputProgramStep] = []
    for step in program:
        current.append(step)
        if step.sample_after:
            trials.append(current)
            current = []
    if current:
        raise ActionPlanError("input program has trailing steps without a sample boundary")
    if not trials:
        raise ActionPlanError("input program contains no action trial boundaries")
    return trials


def _pointer_setup_step(program: list[InputProgramStep]) -> InputProgramStep | None:
    """Return pointer positioning that is setup rather than the causal intervention.

    Playwright's `mouse.click` moves to the target before emitting the button event.
    If pointer motion is itself a mechanic, scoring from a pre-move baseline falsely
    attributes that setup motion to the click. Clicks and drags therefore position the
    pointer before the baseline sample. Pointer-move trials deliberately do not.
    """
    if not program or program[-1].kind not in {"pointer_click", "pointer_drag"}:
        return None
    for step in program:
        if step.command in {"pointer_click", "pointer_down"} and step.pointer_target is not None:
            return step
    return None


def assess_action_trial(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    before_events: list[dict[str, Any]],
    after_events: list[dict[str, Any]],
    before_visible_hash: str,
    after_visible_hash: str,
    required: bool,
    control_before: dict[str, Any] | None = None,
    control_after: dict[str, Any] | None = None,
    control_before_visible_hash: str | None = None,
    control_after_visible_hash: str | None = None,
) -> tuple[bool, bool, bool, bool, list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    if before is None or after is None:
        return False, False, False, False, ["action causality requires before/after telemetry"], warnings

    action_delta = _delta(before, after, "action_count")
    accepted_event_delta = _event_count(after_events, "action_accepted") - _event_count(before_events, "action_accepted")
    accepted = (action_delta is not None and action_delta > 0) or accepted_event_delta > 0

    # Self-reported acknowledgement fields cannot certify their own causal effect.
    # In particular action_count, last_action_ms, core_mechanic_activations and
    # state_hash are trivial for generated code to increment on any event. They remain
    # diagnostic output, but a required binding must alter stronger game semantics or
    # independent pixels to count as meaningful.
    meaningful_state_change = _causal_semantic_change(before, after, control_before, control_after)
    active_visual_change = before_visible_hash != after_visible_hash
    matched_visual_change = (
        control_before_visible_hash is not None
        and control_after_visible_hash is not None
        and control_before_visible_hash != control_after_visible_hash
    )
    independent_visual_change = active_visual_change and not matched_visual_change

    if control_before is not None and control_after is not None:
        if _transition_changed(control_before, control_after):
            warnings.append("matched idle trial changed gameplay state; active effect was baseline-subtracted")
        if matched_visual_change:
            warnings.append("matched idle trial changed pixels; visual change alone cannot certify this action")

    if required and not accepted:
        violations.append("required advertised binding was not accepted by gameplay")
    if required and not meaningful_state_change and not independent_visual_change:
        violations.append("required advertised binding produced no causal gameplay effect beyond matched idle")
    if accepted and not meaningful_state_change and not independent_visual_change:
        warnings.append("input was acknowledged but only bookkeeping or matched-idle effects changed")

    ok = not violations
    return ok, accepted, meaningful_state_change, independent_visual_change, sorted(set(violations)), sorted(set(warnings))


def summarize_action_trials(trials: list[ActionTrial], browsers: list[str]) -> dict[str, Any]:
    builds: dict[str, list[ActionTrial]] = {}
    for row in trials:
        builds.setdefault(row.build_id, []).append(row)

    build_rows: list[dict[str, Any]] = []
    for build_id, rows in sorted(builds.items()):
        provider = rows[0].provider if rows else "unknown"
        by_action: dict[str, list[ActionTrial]] = {}
        for row in rows:
            by_action.setdefault(row.action_id, []).append(row)

        action_summaries: list[ActionSummary] = []
        for action_id, action_rows in sorted(by_action.items()):
            required = any(row.required for row in action_rows)
            passed = sum(row.ok for row in action_rows)
            failed = len(action_rows) - passed
            no_op = sum((not row.accepted) or (not row.meaningful_state_change and not row.independent_visual_change) for row in action_rows)
            no_op_fraction = round(no_op / len(action_rows), 4) if action_rows else 1.0
            action_summaries.append(ActionSummary(
                action_id=action_id,
                required=required,
                trials=len(action_rows),
                passed_trials=passed,
                failed_trials=failed,
                no_op_fraction=no_op_fraction,
                ok=(failed == 0) if required else True,
            ))

        expected_browsers = set(browsers)
        observed_browsers = {row.browser for row in rows}
        required_trials = [row for row in rows if row.required]
        qualified = (
            bool(required_trials)
            and expected_browsers.issubset(observed_browsers)
            and all(row.ok and row.matched_control for row in required_trials)
        )
        build_rows.append({
            "build_id": build_id,
            "provider": provider,
            "qualified": qualified,
            "browsers": sorted(observed_browsers),
            "actions": [asdict(row) for row in action_summaries],
            "trials": [asdict(row) for row in rows],
        })

    return {
        "browsers": browsers,
        "builds_tested": len(build_rows),
        "causality_method": "fresh-state matched-idle subtraction v1",
        "action_causality_pass_build_ids": [row["build_id"] for row in build_rows if row["qualified"]],
        "action_causality_fail_build_ids": [row["build_id"] for row in build_rows if not row["qualified"]],
        "builds": build_rows,
    }


class ActionCausalityLab(CanvasAwareGameplayEvidenceLab):
    """Measure every authoritative binding independently against a matched idle trial."""

    def __init__(
        self,
        browsers: Iterable[str] = ("chromium",),
        timeout_ms: int = 10_000,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        sample_interval_ms: int = 250,
    ):
        super().__init__(
            browsers=browsers,
            timeout_ms=timeout_ms,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            sample_interval_ms=sample_interval_ms,
        )
        self.action_required: dict[str, bool] = {}
        self.trial_programs: list[list[InputProgramStep]] = []

    def configure_trials(self, game_spec: dict[str, Any]) -> None:
        raw_actions = game_spec.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ActionPlanError("action causality requires non-empty structured GameSpec.actions")
        self.action_required = {
            str(row.get("id") or f"action_{index}"): bool(row.get("required", True))
            for index, row in enumerate(raw_actions)
            if isinstance(row, dict)
        }
        program = compile_input_program(raw_actions, hold_ms=160, max_actions=3)
        self.trial_programs = split_action_trials(program)

    def run(self, builds_root: Path, output_dir: Path, reality_root: Path | None = None) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Action causality evidence requires Playwright.") from exc

        builds = discover_builds(builds_root)
        allowed = _qualified_ids(reality_root)
        if allowed is not None:
            builds = [build for build in builds if str(build.get("build_id")) in allowed]
        if not builds:
            raise ValueError("no eligible byte/browser-qualified builds found for action causality")

        game_spec = _load_game_spec(builds_root)
        self.configure_trials(game_spec)
        output_dir.mkdir(parents=True, exist_ok=True)
        rows: list[ActionTrial] = []
        with sync_playwright() as playwright:
            for build in builds:
                with serve_directory(Path(build["resolved_source_dir"])) as url:
                    for browser_name in self.browsers:
                        for trial_program in self.trial_programs:
                            rows.append(self._run_trial(playwright, browser_name, build, url, trial_program))
                            (output_dir / "action-trials.json").write_text(
                                json.dumps([asdict(row) for row in rows], indent=2) + "\n"
                            )

        summary = summarize_action_trials(rows, self.browsers)
        (output_dir / "action-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def _prepare_page(self, browser, url: str, trial_program: list[InputProgramStep], warnings: list[str]):
        context = browser.new_context(viewport={"width": self.viewport_width, "height": self.viewport_height})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.wait_for_timeout(250)
        surface = page.evaluate(_POINTER_SURFACE_JS)
        if not isinstance(surface, dict):
            context.close()
            raise ActionPlanError("pointer surface probe returned no object")
        surface_width = max(1, int(round(float(surface.get("width") or self.viewport_width))))
        surface_height = max(1, int(round(float(surface.get("height") or self.viewport_height))))
        origin_x = max(0, int(round(float(surface.get("x") or 0))))
        origin_y = max(0, int(round(float(surface.get("y") or 0))))
        if surface.get("source") != "canvas" and any(step.kind.startswith("pointer_") for step in trial_program):
            warnings.append("no visible canvas detected; action trial used viewport pointer fallback")

        setup_step = _pointer_setup_step(trial_program)
        if setup_step is not None and setup_step.pointer_target is not None:
            tx, ty = setup_step.pointer_target
            page.mouse.move(
                origin_x + int(round(tx * surface_width)),
                origin_y + int(round(ty * surface_height)),
            )
            page.wait_for_timeout(max(60, min(160, self.sample_interval_ms)))
        return context, page, surface_width, surface_height, origin_x, origin_y

    def _run_trial(
        self,
        playwright,
        browser_name: str,
        build: dict[str, Any],
        url: str,
        trial_program: list[InputProgramStep],
    ) -> ActionTrial:
        boundary = trial_program[-1]
        required = self.action_required.get(boundary.action_id, True)
        browser = None
        active_context = None
        control_context = None
        warnings: list[str] = []
        started = time.perf_counter()
        try:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=True)
            active_context, page, surface_width, surface_height, origin_x, origin_y = self._prepare_page(
                browser, url, trial_program, warnings
            )
            started = time.perf_counter()
            before, present, schema_version, errors = self._sample(page, started)
            if not present or errors:
                raise ValueError("; ".join(errors or ["missing telemetry API"]))
            if schema_version != "0.1":
                raise ValueError(f"unsupported telemetry schema version: {schema_version!r}")

            after_samples = []
            action_started = time.perf_counter()

            def sample_after() -> None:
                row, _, _, sample_errors = self._sample(page, started)
                if sample_errors:
                    raise ValueError("; ".join(sample_errors))
                after_samples.append(row)

            execute_input_program(
                page,
                trial_program,
                viewport_width=surface_width,
                viewport_height=surface_height,
                pointer_origin_x=origin_x,
                pointer_origin_y=origin_y,
                sample=sample_after,
                settle_ms=max(60, min(160, self.sample_interval_ms)),
            )
            if len(after_samples) != 1:
                raise ValueError(f"action trial expected exactly one boundary sample, got {len(after_samples)}")
            after = after_samples[0]
            response_ms = round((time.perf_counter() - action_started) * 1000, 2)
            active_context.close()
            active_context = None

            # Fresh-state matched null: reproduce loading and non-causal pointer setup,
            # then idle for the observed duration of the intervention. This is a strict
            # lower-bound assay: if ambient animation/timers produce the same effect,
            # the action cannot claim that evidence.
            control_context, control_page, _, _, _, _ = self._prepare_page(
                browser, url, trial_program, warnings
            )
            control_started = time.perf_counter()
            control_before, present, schema_version, control_errors = self._sample(control_page, control_started)
            if not present or control_errors:
                raise ValueError("matched control: " + "; ".join(control_errors or ["missing telemetry API"]))
            if schema_version != "0.1":
                raise ValueError(f"matched control unsupported telemetry schema version: {schema_version!r}")
            control_page.wait_for_timeout(max(1, int(round(response_ms))))
            control_after, _, _, control_errors = self._sample(control_page, control_started)
            if control_errors:
                raise ValueError("matched control: " + "; ".join(control_errors))

            assessed = assess_action_trial(
                before.snapshot,
                after.snapshot,
                before_events=before.events,
                after_events=after.events,
                before_visible_hash=before.visible_hash,
                after_visible_hash=after.visible_hash,
                required=required,
                control_before=control_before.snapshot,
                control_after=control_after.snapshot,
                control_before_visible_hash=control_before.visible_hash,
                control_after_visible_hash=control_after.visible_hash,
            )
            ok, accepted, meaningful_change, visible_change, violations, assessment_warnings = assessed
            warnings.extend(assessment_warnings)
            before_snapshot = before.snapshot or {}
            after_snapshot = after.snapshot or {}
            control_before_snapshot = control_before.snapshot or {}
            control_after_snapshot = control_after.snapshot or {}
            control_semantic = _transition_changed(control_before_snapshot, control_after_snapshot)
            control_visual = control_before.visible_hash != control_after.visible_hash
            control_context.close()
            control_context = None
            return ActionTrial(
                build_id=str(build.get("build_id")),
                provider=str(build.get("provider", "unknown")),
                browser=browser_name,
                action_id=boundary.action_id,
                kind=boundary.kind,
                binding=boundary.binding,
                direction=boundary.direction,
                required=required,
                ok=ok,
                accepted=accepted,
                meaningful_state_change=meaningful_change,
                independent_visual_change=visible_change,
                action_count_delta=_delta(before_snapshot, after_snapshot, "action_count"),
                score_delta=_delta(before_snapshot, after_snapshot, "score"),
                progress_delta=_delta(before_snapshot, after_snapshot, "progress"),
                core_mechanic_delta=_delta(before_snapshot, after_snapshot, "core_mechanic_activations"),
                progression_delta=_delta(before_snapshot, after_snapshot, "progression_transitions"),
                response_ms=response_ms,
                before_state_hash=str(before_snapshot.get("state_hash")) if before_snapshot.get("state_hash") is not None else None,
                after_state_hash=str(after_snapshot.get("state_hash")) if after_snapshot.get("state_hash") is not None else None,
                violations=violations,
                warnings=sorted(set(warnings)),
                matched_control=True,
                control_meaningful_state_change=control_semantic,
                control_visual_change=control_visual,
            )
        except Exception as exc:
            return ActionTrial(
                build_id=str(build.get("build_id")),
                provider=str(build.get("provider", "unknown")),
                browser=browser_name,
                action_id=boundary.action_id,
                kind=boundary.kind,
                binding=boundary.binding,
                direction=boundary.direction,
                required=required,
                ok=False,
                accepted=False,
                meaningful_state_change=False,
                independent_visual_change=False,
                action_count_delta=None,
                score_delta=None,
                progress_delta=None,
                core_mechanic_delta=None,
                progression_delta=None,
                response_ms=round((time.perf_counter() - started) * 1000, 2),
                before_state_hash=None,
                after_state_hash=None,
                violations=[f"{type(exc).__name__}: {exc}"],
                warnings=warnings,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            for context in (active_context, control_context):
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-advertised-control causality probe")
    parser.add_argument("builds")
    parser.add_argument("--out", default="runs/action-causality-latest")
    parser.add_argument("--reality", default=None)
    parser.add_argument("--browsers", default="chromium")
    parser.add_argument("--sample-interval-ms", type=int, default=250)
    args = parser.parse_args()
    browsers = [part.strip() for part in args.browsers.split(",") if part.strip()]
    summary = ActionCausalityLab(
        browsers=browsers,
        sample_interval_ms=args.sample_interval_ms,
    ).run(
        Path(args.builds),
        Path(args.out),
        Path(args.reality) if args.reality else None,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("builds") else 2


if __name__ == "__main__":
    raise SystemExit(main())
