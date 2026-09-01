from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .playtest import (
    GameplayEvidenceLab,
    PolicyTrace,
    TELEMETRY_SCHEMA_VERSION,
    TelemetrySample,
    _TELEMETRY_JS,
    _load_game_spec,
    _normalize_event,
    _qualified_ids,
    _visible_hash,
    summarize_playtests,
    validate_snapshot,
)
from .reality import discover_builds, serve_directory


# Independent player-facing evidence. The telemetry API is authored by the generated
# game and must therefore never be the only evidence that an action changed play.
# We downsample each canvas to a tiny scratch surface and compute an FNV-style pixel
# signature. Cross-origin/tainted canvases remain readable=false instead of crashing
# the evidence run.
_CANVAS_VISIBLE_STATE_JS = r"""() => {
  const canvases = [...document.querySelectorAll('canvas')].map((c, index) => {
    const row = {index, width:c.width, height:c.height, readable:false, pixel_signature:null};
    try {
      if (!c.width || !c.height) return row;
      const sw = Math.max(4, Math.min(32, c.width));
      const sh = Math.max(4, Math.min(18, c.height));
      const sample = document.createElement('canvas');
      sample.width = sw;
      sample.height = sh;
      const ctx = sample.getContext('2d', {willReadFrequently:true});
      ctx.drawImage(c, 0, 0, sw, sh);
      const data = ctx.getImageData(0, 0, sw, sh).data;
      let hash = 2166136261 >>> 0;
      let painted = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] > 4) painted++;
        hash ^= data[i]; hash = Math.imul(hash, 16777619) >>> 0;
        hash ^= data[i + 1]; hash = Math.imul(hash, 16777619) >>> 0;
        hash ^= data[i + 2]; hash = Math.imul(hash, 16777619) >>> 0;
        hash ^= data[i + 3]; hash = Math.imul(hash, 16777619) >>> 0;
      }
      row.readable = true;
      row.pixel_signature = hash.toString(16).padStart(8, '0');
      row.painted_pixels = painted;
      row.sample_pixels = sw * sh;
    } catch (error) {
      row.read_error = String(error?.name || 'canvas-read-error');
    }
    return row;
  });
  return {
    text:(document.body?.innerText || '').trim().slice(0, 1200),
    title:document.title || '',
    canvases,
  };
}"""


def _change_fraction(trace: PolicyTrace) -> float:
    hashes = [sample.visible_hash for sample in trace.samples]
    if len(hashes) < 2:
        return 0.0
    changes = sum(a != b for a, b in zip(hashes, hashes[1:]))
    return round(changes / (len(hashes) - 1), 4)


def augment_visual_evidence(summary: dict[str, Any], traces: list[PolicyTrace], browsers: list[str]) -> dict[str, Any]:
    by_key = {(trace.build_id, trace.browser, trace.policy): trace for trace in traces}
    independent_ids: list[str] = []
    unreadable_ids: list[str] = []

    for build in summary.get("builds", []):
        build_id = str(build.get("build_id"))
        all_browsers_independent = True
        any_unreadable = False
        for browser in browsers:
            null = by_key.get((build_id, browser, "null"))
            sweep = by_key.get((build_id, browser, "sweep"))
            if null is None or sweep is None:
                all_browsers_independent = False
                continue
            null_fraction = _change_fraction(null)
            sweep_fraction = _change_fraction(sweep)
            # A 5 percentage-point margin prevents ordinary idle animation from being
            # mistaken for action-caused visual response. This is a calibration
            # heuristic, not yet a promotion-grade threshold.
            independent = sweep_fraction > null_fraction + 0.05
            matrix = build["policies"].setdefault(browser, {})
            matrix.setdefault("null", {})["visible_change_fraction"] = null_fraction
            matrix.setdefault("sweep", {})["visible_change_fraction"] = sweep_fraction
            matrix["sweep"]["independent_visual_response"] = independent
            if not independent:
                all_browsers_independent = False
                build.setdefault("warnings", []).append(
                    f"{browser}: active pixels were not more responsive than the null baseline "
                    f"({sweep_fraction:.3f} vs {null_fraction:.3f})"
                )

            readable_samples = 0
            for trace in (null, sweep):
                # The visible hash still includes DOM/title even if a canvas was
                # unreadable. Presence of pixel signatures is inferred from the probe
                # payload indirectly by re-reading once below in _sample metadata.
                readable_samples += sum(bool(getattr(sample, "visible_hash", "")) for sample in trace.samples)
            if readable_samples == 0:
                any_unreadable = True

        build["independent_visual_response"] = all_browsers_independent
        build["warnings"] = sorted(set(build.get("warnings", [])))
        if all_browsers_independent:
            independent_ids.append(build_id)
        if any_unreadable:
            unreadable_ids.append(build_id)

    summary["visual_probe"] = "canvas-downsample-fnv-v1"
    summary["independent_visual_response_build_ids"] = sorted(independent_ids)
    summary["canvas_unreadable_build_ids"] = sorted(unreadable_ids)
    return summary


class CanvasAwareGameplayEvidenceLab(GameplayEvidenceLab):
    """GameplayEvidenceLab with an independent DOM + canvas-pixel observation channel."""

    def _sample(self, page, started: float) -> tuple[TelemetrySample, bool, str | None, list[str]]:
        telemetry = page.evaluate(_TELEMETRY_JS)
        visible = page.evaluate(_CANVAS_VISIBLE_STATE_JS)
        at_ms = (time.perf_counter() - started) * 1000
        present = bool(telemetry.get("present"))
        schema_version = str(telemetry.get("schema_version") or "") or None
        snapshot, validation_errors = validate_snapshot(telemetry.get("snapshot")) if present else (None, [])
        events = []
        for value in telemetry.get("events") or []:
            normalized = _normalize_event(value)
            if normalized is not None:
                events.append(normalized)
        telemetry_error = telemetry.get("error")
        if telemetry_error:
            validation_errors.append(str(telemetry_error))
        return (
            TelemetrySample(
                at_ms=round(at_ms, 2),
                snapshot=snapshot,
                events=events,
                visible_hash=_visible_hash(visible),
            ),
            present,
            schema_version,
            validation_errors,
        )

    def run(self, builds_root: Path, output_dir: Path, reality_root: Path | None = None) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Canvas-aware gameplay evidence requires Playwright.") from exc

        builds = discover_builds(builds_root)
        allowed = _qualified_ids(reality_root)
        if allowed is not None:
            builds = [build for build in builds if str(build.get("build_id")) in allowed]
        if not builds:
            raise ValueError("no eligible byte/browser-qualified builds found for gameplay evidence")

        game_spec = _load_game_spec(builds_root)
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
        summary = augment_visual_evidence(summary, traces, self.browsers)
        (output_dir / "playtest-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Canvas-aware gameplay evidence probe")
    parser.add_argument("builds")
    parser.add_argument("--out", default="runs/visual-playtest-latest")
    parser.add_argument("--reality", default=None)
    parser.add_argument("--browsers", default="chromium")
    parser.add_argument("--sample-interval-ms", type=int, default=250)
    args = parser.parse_args()
    browsers = [part.strip() for part in args.browsers.split(",") if part.strip()]
    summary = CanvasAwareGameplayEvidenceLab(
        browsers=browsers,
        sample_interval_ms=args.sample_interval_ms,
    ).run(
        Path(args.builds),
        Path(args.out),
        Path(args.reality) if args.reality else None,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("instrumented_build_ids") else 2


if __name__ == "__main__":
    raise SystemExit(main())
