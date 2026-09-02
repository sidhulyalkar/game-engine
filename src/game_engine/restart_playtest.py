from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .action_policy import ActionPlanError, execute_input_program
from .playtest import _load_game_spec, _qualified_ids
from .reality import discover_builds, serve_directory
from .structured_playtest import _POINTER_SURFACE_JS
from .visual_playtest import CanvasAwareGameplayEvidenceLab


@dataclass(slots=True)
class RestartEvidence:
    build_id: str
    provider: str
    browser: str
    binding: str
    ok: bool
    pre_restart_mutated: bool
    independent_visual_mutation: bool
    restart_visual_response: bool
    visual_returned_to_baseline: bool
    restart_event_seen: bool
    baseline_snapshot: dict[str, Any] | None
    before_restart_snapshot: dict[str, Any] | None
    after_restart_snapshot: dict[str, Any] | None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _near(a: Any, b: Any, tolerance: float = 1e-6) -> bool:
    return _finite(a) and _finite(b) and abs(float(a) - float(b)) <= tolerance


def _changed(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    return before.get(key) != after.get(key)


def assess_restart(
    baseline: dict[str, Any] | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    restart_events: list[dict[str, Any]],
    baseline_visible_hash: str,
    before_visible_hash: str,
    after_visible_hash: str,
) -> tuple[bool, bool, bool, bool, bool, list[str], list[str]]:
    """Cross-check a reset against both game telemetry and player-visible evidence."""
    violations: list[str] = []
    warnings: list[str] = []
    if baseline is None or before is None or after is None:
        return False, False, False, False, False, ["restart evidence requires baseline/before/after telemetry"], warnings

    mutation_fields = (
        "score", "progress", "action_count", "core_mechanic_activations",
        "entity_count", "state_hash", "state", "game_over",
    )
    pre_restart_mutated = any(_changed(baseline, before, key) for key in mutation_fields)
    if not pre_restart_mutated:
        violations.append("advertised actions did not mutate measurable state before restart")

    independent_visual_mutation = baseline_visible_hash != before_visible_hash
    if not independent_visual_mutation:
        violations.append("advertised actions did not visibly mutate the game before restart")

    restart_visual_response = before_visible_hash != after_visible_hash
    if not restart_visual_response:
        violations.append("restart produced no independent player-visible response")

    visual_returned_to_baseline = after_visible_hash == baseline_visible_hash
    if not visual_returned_to_baseline:
        warnings.append("post-restart pixels did not exactly match the initial sample; animation may explain drift")

    if after.get("state") != "playing":
        violations.append(f"restart state is {after.get('state')!r}, expected 'playing'")
    if after.get("alive") is not True:
        violations.append("restart did not restore alive=true")
    if after.get("game_over") is not False:
        violations.append("restart did not clear game_over")

    before_count = before.get("restart_count")
    after_count = after.get("restart_count")
    if not _finite(before_count) or not _finite(after_count) or int(float(after_count)) != int(float(before_count)) + 1:
        violations.append("restart_count did not increment exactly once")

    for key in ("score", "progress", "action_count"):
        if key in baseline and not _near(after.get(key), baseline.get(key)):
            violations.append(f"restart did not restore {key} to fresh-run baseline")

    baseline_last_action = baseline.get("last_action_ms")
    after_last_action = after.get("last_action_ms")
    if baseline_last_action is None and after_last_action is not None:
        violations.append("restart left stale last_action_ms instead of fresh input state")

    baseline_entities = baseline.get("entity_count")
    after_entities = after.get("entity_count")
    if _finite(baseline_entities) and _finite(after_entities):
        allowed_drift = max(2.0, abs(float(baseline_entities)) * 0.25)
        if abs(float(after_entities) - float(baseline_entities)) > allowed_drift:
            violations.append("restart entity_count is not coherent with fresh-run baseline")

    before_elapsed = before.get("elapsed_ms")
    after_elapsed = after.get("elapsed_ms")
    if _finite(before_elapsed) and _finite(after_elapsed) and float(after_elapsed) >= float(before_elapsed):
        violations.append("restart did not reset run elapsed time")

    restart_event_seen = any(str(row.get("type")) == "restart" for row in restart_events)
    if not restart_event_seen:
        violations.append("restart event missing from telemetry event stream")

    if before.get("state_hash") is not None and after.get("state_hash") == before.get("state_hash"):
        violations.append("state_hash stayed identical across restart")

    ok = not violations
    return (
        ok,
        pre_restart_mutated,
        independent_visual_mutation,
        restart_visual_response,
        visual_returned_to_baseline,
        restart_event_seen,
        sorted(set(violations)),
        sorted(set(warnings)),
    )


class RestartEvidenceLab(CanvasAwareGameplayEvidenceLab):
    """Exercise the deterministic GameSpec restart binding after real gameplay input."""

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
        self.restart_binding = "R"

    def configure_restart(self, game_spec: dict[str, Any]) -> None:
        self.configure_action_program(game_spec)
        if self.active_program is None:
            raise ActionPlanError("restart evidence requires structured GameSpec actions to mutate the game")
        state_machine = game_spec.get("state_machine")
        if not isinstance(state_machine, dict):
            raise ActionPlanError("GameSpec.state_machine must be an object")
        binding = str(state_machine.get("restart_binding") or "").strip()
        if not binding:
            raise ActionPlanError("GameSpec.state_machine.restart_binding is required")
        self.restart_binding = binding

    def run(self, builds_root: Path, output_dir: Path, reality_root: Path | None = None) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Restart evidence requires Playwright.") from exc

        builds = discover_builds(builds_root)
        allowed = _qualified_ids(reality_root)
        if allowed is not None:
            builds = [build for build in builds if str(build.get("build_id")) in allowed]
        if not builds:
            raise ValueError("no eligible byte/browser-qualified builds found for restart evidence")

        game_spec = _load_game_spec(builds_root)
        self.configure_restart(game_spec)
        output_dir.mkdir(parents=True, exist_ok=True)
        rows: list[RestartEvidence] = []
        with sync_playwright() as playwright:
            for build in builds:
                with serve_directory(Path(build["resolved_source_dir"])) as url:
                    for browser_name in self.browsers:
                        rows.append(self._run_restart_case(playwright, browser_name, build, url))
                        (output_dir / "restart-cases.json").write_text(
                            json.dumps([asdict(row) for row in rows], indent=2) + "\n"
                        )

        passed = sorted({row.build_id for row in rows if row.ok})
        failed = sorted({row.build_id for row in rows if not row.ok})
        summary = {
            "browsers": self.browsers,
            "restart_binding": self.restart_binding,
            "builds_tested": len({row.build_id for row in rows}),
            "restart_pass_build_ids": passed,
            "restart_fail_build_ids": failed,
            "cases": [asdict(row) for row in rows],
        }
        (output_dir / "restart-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def _run_restart_case(self, playwright, browser_name: str, build: dict, url: str) -> RestartEvidence:
        browser = None
        warnings: list[str] = []
        try:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=True)
            context = browser.new_context(viewport={"width": self.viewport_width, "height": self.viewport_height})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(250)
            started = time.perf_counter()

            baseline, _, _, baseline_errors = self._sample(page, started)
            if baseline_errors:
                raise ValueError("; ".join(baseline_errors))

            surface = page.evaluate(_POINTER_SURFACE_JS)
            if not isinstance(surface, dict):
                raise ActionPlanError("pointer surface probe returned no object")
            surface_width = max(1, int(round(float(surface.get("width") or self.viewport_width))))
            surface_height = max(1, int(round(float(surface.get("height") or self.viewport_height))))
            origin_x = max(0, int(round(float(surface.get("x") or 0))))
            origin_y = max(0, int(round(float(surface.get("y") or 0))))
            if surface.get("source") != "canvas" and any(
                step.kind.startswith("pointer_") for step in (self.active_program or [])
            ):
                warnings.append("no visible canvas detected; structured pointer actions used viewport fallback")

            action_samples = []

            def sample_action() -> None:
                row, _, _, errors = self._sample(page, started)
                if errors:
                    raise ValueError("; ".join(errors))
                action_samples.append(row)

            execute_input_program(
                page,
                self.active_program or [],
                viewport_width=surface_width,
                viewport_height=surface_height,
                pointer_origin_x=origin_x,
                pointer_origin_y=origin_y,
                sample=sample_action,
                settle_ms=max(60, min(160, self.sample_interval_ms)),
            )
            if not action_samples:
                raise ValueError("structured action program produced no sample boundary")
            before = action_samples[-1]

            page.keyboard.press(self.restart_binding)
            page.wait_for_timeout(max(80, min(200, self.sample_interval_ms)))
            after, _, _, after_errors = self._sample(page, started)
            if after_errors:
                raise ValueError("; ".join(after_errors))

            assessed = assess_restart(
                baseline.snapshot,
                before.snapshot,
                after.snapshot,
                restart_events=after.events,
                baseline_visible_hash=baseline.visible_hash,
                before_visible_hash=before.visible_hash,
                after_visible_hash=after.visible_hash,
            )
            (
                ok,
                pre_restart_mutated,
                independent_visual_mutation,
                restart_visual_response,
                visual_returned_to_baseline,
                restart_event_seen,
                violations,
                assessment_warnings,
            ) = assessed
            warnings.extend(assessment_warnings)
            context.close()
            return RestartEvidence(
                build_id=str(build.get("build_id")),
                provider=str(build.get("provider", "unknown")),
                browser=browser_name,
                binding=self.restart_binding,
                ok=ok,
                pre_restart_mutated=pre_restart_mutated,
                independent_visual_mutation=independent_visual_mutation,
                restart_visual_response=restart_visual_response,
                visual_returned_to_baseline=visual_returned_to_baseline,
                restart_event_seen=restart_event_seen,
                baseline_snapshot=baseline.snapshot,
                before_restart_snapshot=before.snapshot,
                after_restart_snapshot=after.snapshot,
                violations=violations,
                warnings=sorted(set(warnings)),
            )
        except Exception as exc:
            return RestartEvidence(
                build_id=str(build.get("build_id")),
                provider=str(build.get("provider", "unknown")),
                browser=browser_name,
                binding=self.restart_binding,
                ok=False,
                pre_restart_mutated=False,
                independent_visual_mutation=False,
                restart_visual_response=False,
                visual_returned_to_baseline=False,
                restart_event_seen=False,
                baseline_snapshot=None,
                before_restart_snapshot=None,
                after_restart_snapshot=None,
                violations=[f"{type(exc).__name__}: {exc}"],
                warnings=warnings,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh-run restart evidence probe")
    parser.add_argument("builds")
    parser.add_argument("--out", default="runs/restart-evidence-latest")
    parser.add_argument("--reality", default=None)
    parser.add_argument("--browsers", default="chromium")
    parser.add_argument("--sample-interval-ms", type=int, default=250)
    args = parser.parse_args()
    browsers = [part.strip() for part in args.browsers.split(",") if part.strip()]
    summary = RestartEvidenceLab(
        browsers=browsers,
        sample_interval_ms=args.sample_interval_ms,
    ).run(
        Path(args.builds),
        Path(args.out),
        Path(args.reality) if args.reality else None,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("cases") else 2


if __name__ == "__main__":
    raise SystemExit(main())
