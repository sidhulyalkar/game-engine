from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from .action_policy import (
    ActionPlanError,
    InputProgramStep,
    action_boundaries,
    compile_input_program,
    execute_input_program,
)
from .playtest import GameplayEvidenceLab, InputAction, PolicyTrace, _load_game_spec, _summarize_trace, _qualified_ids, summarize_playtests
from .reality import discover_builds, serve_directory


_POINTER_SURFACE_JS = r"""() => {
  const vw = Math.max(1, window.innerWidth || document.documentElement.clientWidth || 1);
  const vh = Math.max(1, window.innerHeight || document.documentElement.clientHeight || 1);
  const candidates = [...document.querySelectorAll('canvas')].map((canvas, index) => {
    const r = canvas.getBoundingClientRect();
    const left = Math.max(0, r.left);
    const top = Math.max(0, r.top);
    const right = Math.min(vw, r.right);
    const bottom = Math.min(vh, r.bottom);
    const width = Math.max(0, right - left);
    const height = Math.max(0, bottom - top);
    return {index, x:left, y:top, width, height, area:width * height};
  }).filter(row => row.area > 16);
  candidates.sort((a, b) => b.area - a.area);
  if (candidates.length) return {...candidates[0], source:'canvas'};
  return {index:null, x:0, y:0, width:vw, height:vh, area:vw * vh, source:'viewport'};
}"""


class StructuredGameplayEvidenceLab(GameplayEvidenceLab):
    """Gameplay Evidence Lab driven by the authoritative structured GameSpec actions.

    New GameSpec artifacts must be tested with their declared controls. Legacy specs
    without structured actions retain the old generic sweep, but that fallback is
    explicitly labeled in evidence so it cannot masquerade as control-aware testing.
    """

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
        self.active_program: list[InputProgramStep] | None = None
        self.active_policy_source = "legacy-generic-sweep"

    def configure_action_program(self, game_spec: dict[str, Any]) -> None:
        raw_actions = game_spec.get("actions")
        if raw_actions is None or raw_actions == []:
            self.active_program = None
            self.active_policy_source = "legacy-generic-sweep"
            return
        if not isinstance(raw_actions, list):
            raise ActionPlanError("GameSpec.actions must be a list")
        program = compile_input_program(raw_actions, hold_ms=160, max_actions=3)
        if not program:
            required = [row for row in raw_actions if isinstance(row, dict) and row.get("required", True)]
            if required:
                raise ActionPlanError("GameSpec required actions compiled to an empty input program")
        self.active_program = program
        self.active_policy_source = "gamespec-actions"

    def _decorate_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        summary["active_policy_source"] = self.active_policy_source
        summary["action_program"] = [step.to_dict() for step in (self.active_program or [])]
        summary["action_boundaries"] = action_boundaries(self.active_program or [])
        return summary

    def run(self, builds_root: Path, output_dir: Path, reality_root: Path | None = None) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Gameplay Evidence Lab requires Playwright. Install with `pip install playwright` "
                "and the requested browser engines."
            ) from exc

        builds = discover_builds(builds_root)
        allowed = _qualified_ids(reality_root)
        if allowed is not None:
            builds = [build for build in builds if str(build.get("build_id")) in allowed]
        if not builds:
            raise ValueError("no eligible byte/browser-qualified builds found for gameplay evidence")

        game_spec = _load_game_spec(builds_root)
        self.configure_action_program(game_spec)
        output_dir.mkdir(parents=True, exist_ok=True)
        traces: list[PolicyTrace] = []
        with sync_playwright() as playwright:
            for build in builds:
                with serve_directory(Path(build["resolved_source_dir"])) as url:
                    for browser_name in self.browsers:
                        traces.append(self._run_policy(playwright, browser_name, build, url, "null"))
                        traces.append(self._run_policy(playwright, browser_name, build, url, "sweep"))
                        self._write_traces(output_dir, traces)

        summary = summarize_playtests(traces, self.browsers, game_spec)
        summary = self._decorate_summary(summary)
        (output_dir / "playtest-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def _run_policy(self, playwright, browser_name: str, build: dict, url: str, policy: str) -> PolicyTrace:
        if policy != "sweep" or self.active_program is None:
            trace = super()._run_policy(playwright, browser_name, build, url, policy)
            if policy == "sweep" and self.active_program is None:
                trace.warnings = sorted(set([
                    *trace.warnings,
                    "legacy GameSpec has no structured actions; generic sweep used",
                ]))
            return trace

        actions: list[InputAction] = []
        samples = []
        violations: list[str] = []
        warnings: list[str] = []
        browser = None
        telemetry_present = False
        schema_version: str | None = None
        schema_valid = True
        started = time.perf_counter()
        try:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=True)
            context = browser.new_context(viewport={"width": self.viewport_width, "height": self.viewport_height})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(250)
            started = time.perf_counter()

            def sample() -> None:
                nonlocal telemetry_present, schema_version, schema_valid
                row, present, version, errors = self._sample(page, started)
                samples.append(row)
                telemetry_present = telemetry_present or present
                schema_version = schema_version or version
                if errors:
                    schema_valid = False
                    violations.extend(errors)

            def mark(action: str) -> None:
                actions.append(InputAction(round((time.perf_counter() - started) * 1000, 2), action))

            sample()
            surface = page.evaluate(_POINTER_SURFACE_JS)
            if not isinstance(surface, dict):
                raise ActionPlanError("pointer surface probe returned no object")
            surface_width = max(1, int(round(float(surface.get("width") or self.viewport_width))))
            surface_height = max(1, int(round(float(surface.get("height") or self.viewport_height))))
            origin_x = max(0, int(round(float(surface.get("x") or 0))))
            origin_y = max(0, int(round(float(surface.get("y") or 0))))
            if surface.get("source") != "canvas" and any(
                step.kind.startswith("pointer_") for step in self.active_program
            ):
                warnings.append("no visible canvas detected; structured pointer actions used viewport fallback")
            execute_input_program(
                page,
                self.active_program,
                viewport_width=surface_width,
                viewport_height=surface_height,
                pointer_origin_x=origin_x,
                pointer_origin_y=origin_y,
                mark=mark,
                sample=sample,
                settle_ms=max(60, min(160, self.sample_interval_ms)),
            )
            context.close()
        except Exception as exc:
            violations.append(f"{type(exc).__name__}: {exc}")
            return PolicyTrace(
                build_id=str(build.get("build_id")),
                provider=str(build.get("provider", "unknown")),
                browser=browser_name,
                policy=policy,
                ok=False,
                telemetry_present=telemetry_present,
                schema_version=schema_version,
                schema_valid=False,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                actions=actions,
                samples=samples,
                violations=sorted(set(violations)),
                warnings=warnings,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

        if not telemetry_present:
            violations.append("missing window.__GAME_ENGINE_TELEMETRY__")
            schema_valid = False
        from .playtest import TELEMETRY_SCHEMA_VERSION
        if schema_version not in {TELEMETRY_SCHEMA_VERSION}:
            violations.append(f"unsupported telemetry schema version: {schema_version!r}")
            schema_valid = False

        trace = PolicyTrace(
            build_id=str(build.get("build_id")),
            provider=str(build.get("provider", "unknown")),
            browser=browser_name,
            policy=policy,
            ok=not violations,
            telemetry_present=telemetry_present,
            schema_version=schema_version,
            schema_valid=schema_valid,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            actions=actions,
            samples=samples,
            violations=sorted(set(violations)),
            warnings=warnings,
        )
        return _summarize_trace(trace)
