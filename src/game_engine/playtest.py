from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .reality import discover_builds, serve_directory


TELEMETRY_SCHEMA_VERSION = "0.1"
SNAPSHOT_FIELDS = (
    "elapsed_ms",
    "tick",
    "state",
    "alive",
    "game_over",
    "score",
    "progress",
    "restart_count",
    "entity_count",
    "action_count",
    "last_action_ms",
    "core_mechanic_activations",
    "progression_transitions",
    "state_hash",
)

_TELEMETRY_JS = r"""() => {
  const api = window.__GAME_ENGINE_TELEMETRY__;
  if (!api) return {present:false, schema_version:null, snapshot:null, events:[]};
  let snapshot = null;
  let events = [];
  try {
    snapshot = typeof api.snapshot === 'function' ? api.snapshot() : (api.snapshot || null);
  } catch (error) {
    return {present:true, schema_version:String(api.schema_version || api.version || ''), snapshot:null, events:[], error:`snapshot:${error}`};
  }
  try {
    const raw = typeof api.events === 'function' ? api.events() : (api.events || []);
    if (Array.isArray(raw)) events = raw.slice(-256);
  } catch (error) {
    return {present:true, schema_version:String(api.schema_version || api.version || ''), snapshot, events:[], error:`events:${error}`};
  }
  return {
    present:true,
    schema_version:String(api.schema_version || api.version || ''),
    snapshot,
    events,
  };
}"""

_VISIBLE_STATE_JS = r"""() => ({
  text:(document.body?.innerText || '').trim().slice(0, 1200),
  title:document.title || '',
  canvases:[...document.querySelectorAll('canvas')].map(c => ({width:c.width,height:c.height}))
})"""


@dataclass(slots=True)
class InputAction:
    at_ms: float
    action: str


@dataclass(slots=True)
class TelemetrySample:
    at_ms: float
    snapshot: dict[str, Any] | None
    events: list[dict[str, Any]]
    visible_hash: str


@dataclass(slots=True)
class PolicyTrace:
    build_id: str
    provider: str
    browser: str
    policy: str
    ok: bool
    telemetry_present: bool
    schema_version: str | None
    schema_valid: bool
    duration_ms: float
    actions: list[InputAction] = field(default_factory=list)
    samples: list[TelemetrySample] = field(default_factory=list)
    initial_snapshot: dict[str, Any] | None = None
    final_snapshot: dict[str, Any] | None = None
    visible_change: bool = False
    meaningful_state_changes: int = 0
    score_delta: float | None = None
    progress_delta: float | None = None
    max_entity_count: int | None = None
    core_mechanic_activations: int | None = None
    progression_transitions: int | None = None
    first_progress_ms: float | None = None
    first_terminal_ms: float | None = None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class BuildPlaytestSummary:
    build_id: str
    provider: str
    browsers: list[str]
    instrumented: bool
    mechanically_observable: bool
    cross_browser_divergence: bool
    violations: list[str]
    warnings: list[str]
    policies: dict[str, dict[str, Any]]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_snapshot(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate only the portable player-evidence subset of self-reported telemetry."""
    if not isinstance(value, dict):
        return None, ["snapshot must be an object"]

    errors: list[str] = []
    snapshot = {key: value.get(key) for key in SNAPSHOT_FIELDS if key in value}

    state = snapshot.get("state")
    if state is not None and not isinstance(state, str):
        errors.append("state must be a string")

    for key in ("alive", "game_over"):
        if key in snapshot and not isinstance(snapshot[key], bool):
            errors.append(f"{key} must be boolean")

    for key in (
        "elapsed_ms", "tick", "score", "progress", "restart_count", "entity_count",
        "action_count", "last_action_ms", "core_mechanic_activations", "progression_transitions",
    ):
        if key in snapshot and snapshot[key] is not None and not _finite_number(snapshot[key]):
            errors.append(f"{key} must be a finite number or null")

    if "progress" in snapshot and _finite_number(snapshot.get("progress")):
        progress = float(snapshot["progress"])
        if progress < -0.001 or progress > 1.001:
            errors.append("progress should be normalized to 0..1")

    if "state_hash" in snapshot and snapshot["state_hash"] is not None and not isinstance(snapshot["state_hash"], str):
        errors.append("state_hash must be a string or null")

    required_any = {
        "elapsed_ms",
        "state",
        "score",
        "progress",
        "entity_count",
        "action_count",
        "core_mechanic_activations",
    }
    missing = sorted(required_any - set(snapshot))
    if missing:
        errors.append("missing required telemetry fields: " + ", ".join(missing))

    return snapshot, errors


def _normalize_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    event_type = value.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        return None
    result = {"type": event_type.strip()[:80]}
    if _finite_number(value.get("at_ms")):
        result["at_ms"] = round(float(value["at_ms"]), 3)
    elif _finite_number(value.get("t")):
        result["at_ms"] = round(float(value["t"]), 3)
    return result


def _visible_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _meaningful_signature(snapshot: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if snapshot is None:
        return None
    return (
        snapshot.get("state"),
        snapshot.get("alive"),
        snapshot.get("game_over"),
        snapshot.get("score"),
        snapshot.get("progress"),
        snapshot.get("entity_count"),
        snapshot.get("core_mechanic_activations"),
        snapshot.get("progression_transitions"),
    )


def _delta(start: dict[str, Any] | None, end: dict[str, Any] | None, key: str) -> float | None:
    if start is None or end is None:
        return None
    a, b = start.get(key), end.get(key)
    if not _finite_number(a) or not _finite_number(b):
        return None
    return round(float(b) - float(a), 6)


def _first_change_ms(samples: list[TelemetrySample], key: str) -> float | None:
    if not samples or samples[0].snapshot is None:
        return None
    baseline = samples[0].snapshot.get(key)
    for sample in samples[1:]:
        if sample.snapshot is not None and sample.snapshot.get(key) != baseline:
            return round(sample.at_ms, 2)
    return None


def _first_terminal_ms(samples: list[TelemetrySample]) -> float | None:
    for sample in samples:
        snap = sample.snapshot or {}
        state = str(snap.get("state") or "").lower()
        if snap.get("game_over") is True or state in {"dead", "won", "win", "game_over"}:
            return round(sample.at_ms, 2)
    return None


def _max_numeric(samples: list[TelemetrySample], key: str) -> int | None:
    values = [
        int(float(sample.snapshot[key]))
        for sample in samples
        if sample.snapshot is not None and _finite_number(sample.snapshot.get(key))
    ]
    return max(values) if values else None


def _summarize_trace(trace: PolicyTrace) -> PolicyTrace:
    valid_samples = [sample for sample in trace.samples if sample.snapshot is not None]
    if valid_samples:
        trace.initial_snapshot = valid_samples[0].snapshot
        trace.final_snapshot = valid_samples[-1].snapshot
        signatures = [_meaningful_signature(sample.snapshot) for sample in valid_samples]
        trace.meaningful_state_changes = sum(a != b for a, b in zip(signatures, signatures[1:]))
        trace.score_delta = _delta(trace.initial_snapshot, trace.final_snapshot, "score")
        trace.progress_delta = _delta(trace.initial_snapshot, trace.final_snapshot, "progress")
        trace.max_entity_count = _max_numeric(valid_samples, "entity_count")
        trace.core_mechanic_activations = _max_numeric(valid_samples, "core_mechanic_activations")
        trace.progression_transitions = _max_numeric(valid_samples, "progression_transitions")
        trace.first_progress_ms = _first_change_ms(valid_samples, "progress")
        trace.first_terminal_ms = _first_terminal_ms(valid_samples)
    hashes = [sample.visible_hash for sample in trace.samples]
    trace.visible_change = len(set(hashes)) > 1
    return trace


def _load_game_spec(builds_root: Path) -> dict[str, Any]:
    path = builds_root / "game-spec.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _qualified_ids(reality_root: Path | None) -> set[str] | None:
    if reality_root is None:
        return None
    path = reality_root / "qualification.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return {str(value) for value in payload.get("full_pass_build_ids", [])}


def _entity_soft_limit(game_spec: dict[str, Any]) -> int | None:
    bounds = game_spec.get("state_bounds")
    if not isinstance(bounds, dict):
        return None
    relevant = []
    for key, value in bounds.items():
        if any(token in str(key) for token in ("hazard", "enemy", "particle", "trail", "timer", "event")) and _finite_number(value):
            relevant.append(max(0, int(float(value))))
    if not relevant:
        return None
    return sum(relevant) + 16


def _trace_fingerprint(trace: PolicyTrace) -> str:
    rows = []
    for sample in trace.samples:
        snap = sample.snapshot or {}
        rows.append({
            "state": snap.get("state"),
            "alive": snap.get("alive"),
            "game_over": snap.get("game_over"),
            "score": snap.get("score"),
            "progress": snap.get("progress"),
            "core": snap.get("core_mechanic_activations"),
            "progression": snap.get("progression_transitions"),
        })
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def summarize_playtests(traces: list[PolicyTrace], browsers: list[str], game_spec: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[PolicyTrace]] = {}
    for trace in traces:
        grouped.setdefault(trace.build_id, []).append(trace)

    expected = set(browsers)
    build_summaries: list[BuildPlaytestSummary] = []
    for build_id, rows in grouped.items():
        provider = rows[0].provider if rows else "unknown"
        violations: list[str] = []
        warnings: list[str] = []
        matrix: dict[str, dict[str, Any]] = {}
        instrumented_browsers: set[str] = set()
        observable_browsers: set[str] = set()
        fingerprints: dict[str, str] = {}
        entity_limit = _entity_soft_limit(game_spec)

        by_browser: dict[str, list[PolicyTrace]] = {}
        for row in rows:
            by_browser.setdefault(row.browser, []).append(row)
            matrix.setdefault(row.browser, {})[row.policy] = {
                "ok": row.ok,
                "telemetry_present": row.telemetry_present,
                "schema_valid": row.schema_valid,
                "visible_change": row.visible_change,
                "meaningful_state_changes": row.meaningful_state_changes,
                "score_delta": row.score_delta,
                "progress_delta": row.progress_delta,
                "core_mechanic_activations": row.core_mechanic_activations,
                "first_terminal_ms": row.first_terminal_ms,
            }
            violations.extend(f"{row.browser}/{row.policy}: {v}" for v in row.violations)
            warnings.extend(f"{row.browser}/{row.policy}: {w}" for w in row.warnings)

        for browser, browser_rows in by_browser.items():
            policies = {row.policy: row for row in browser_rows}
            if {"null", "sweep"}.issubset(policies):
                null = policies["null"]
                sweep = policies["sweep"]
                if null.telemetry_present and sweep.telemetry_present and null.schema_valid and sweep.schema_valid:
                    instrumented_browsers.add(browser)
                active_signal = (
                    sweep.meaningful_state_changes > 0
                    or (sweep.score_delta or 0) != 0
                    or (sweep.progress_delta or 0) != 0
                    or (sweep.core_mechanic_activations or 0) > 0
                    or sweep.visible_change
                )
                if active_signal and sweep.ok:
                    observable_browsers.add(browser)
                if sweep.meaningful_state_changes <= null.meaningful_state_changes and not sweep.visible_change:
                    warnings.append(f"{browser}: active sweep produced no stronger observable response than null policy")
                if (
                    sweep.first_terminal_ms is not None
                    and sweep.first_terminal_ms < 3000
                    and (sweep.core_mechanic_activations or 0) == 0
                ):
                    warnings.append(f"{browser}: terminal state reached before 3s without a core-mechanic activation")
                if entity_limit is not None and sweep.max_entity_count is not None and sweep.max_entity_count > entity_limit:
                    violations.append(
                        f"{browser}: entity_count {sweep.max_entity_count} exceeds conservative GameSpec evidence limit {entity_limit}"
                    )
                fingerprints[browser] = _trace_fingerprint(sweep)

        cross_browser_divergence = len(set(fingerprints.values())) > 1 if len(fingerprints) > 1 else False
        if cross_browser_divergence:
            warnings.append("deterministic sweep telemetry differs across browsers")

        instrumented = bool(expected) and expected.issubset(instrumented_browsers)
        mechanically_observable = bool(expected) and expected.issubset(observable_browsers) and not violations
        build_summaries.append(BuildPlaytestSummary(
            build_id=build_id,
            provider=provider,
            browsers=sorted(by_browser),
            instrumented=instrumented,
            mechanically_observable=mechanically_observable,
            cross_browser_divergence=cross_browser_divergence,
            violations=sorted(set(violations)),
            warnings=sorted(set(warnings)),
            policies=matrix,
        ))

    build_summaries.sort(key=lambda row: (not row.instrumented, not row.mechanically_observable, row.build_id))
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "browsers": browsers,
        "builds_tested": len(build_summaries),
        "instrumented_build_ids": [row.build_id for row in build_summaries if row.instrumented],
        "mechanically_observable_build_ids": [row.build_id for row in build_summaries if row.mechanically_observable],
        "cross_browser_divergence_build_ids": [row.build_id for row in build_summaries if row.cross_browser_divergence],
        "builds": [asdict(row) for row in build_summaries],
    }


class GameplayEvidenceLab:
    """Run conservative mechanical-evidence policies against browser-qualified builds.

    This layer intentionally does not judge fun. It establishes whether a generated
    prototype exposes coherent telemetry and whether deterministic player input can
    produce observable/measurable state changes beyond an idle baseline.
    """

    def __init__(
        self,
        browsers: Iterable[str] = ("chromium",),
        timeout_ms: int = 10_000,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        sample_interval_ms: int = 250,
    ):
        self.browsers = [browser.strip() for browser in browsers if browser.strip()]
        self.timeout_ms = timeout_ms
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.sample_interval_ms = max(80, sample_interval_ms)

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
        (output_dir / "playtest-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def _write_traces(self, output_dir: Path, traces: list[PolicyTrace]) -> None:
        payload = [asdict(trace) for trace in traces]
        (output_dir / "playtraces.json").write_text(json.dumps(payload, indent=2) + "\n")
        (output_dir / "playtraces.jsonl").write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in payload)
        )

    def _sample(self, page, started: float) -> tuple[TelemetrySample, bool, str | None, list[str]]:
        telemetry = page.evaluate(_TELEMETRY_JS)
        visible = page.evaluate(_VISIBLE_STATE_JS)
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

    def _run_policy(self, playwright, browser_name: str, build: dict, url: str, policy: str) -> PolicyTrace:
        actions: list[InputAction] = []
        samples: list[TelemetrySample] = []
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

            sample()
            if policy == "null":
                for _ in range(8):
                    page.wait_for_timeout(self.sample_interval_ms)
                    sample()
            elif policy == "sweep":
                cx, cy = self.viewport_width // 2, self.viewport_height // 2

                def mark(action: str) -> None:
                    actions.append(InputAction(round((time.perf_counter() - started) * 1000, 2), action))

                page.mouse.click(cx, cy)
                mark("click:center")
                page.wait_for_timeout(self.sample_interval_ms)
                sample()

                for key in ("w", "a", "s", "d", "ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight", "Space"):
                    page.keyboard.down(key)
                    mark(f"keydown:{key}")
                    page.wait_for_timeout(140)
                    page.keyboard.up(key)
                    mark(f"keyup:{key}")
                    page.wait_for_timeout(90)
                    sample()

                for x, y, label in (
                    (int(self.viewport_width * 0.75), cy, "right"),
                    (int(self.viewport_width * 0.25), cy, "left"),
                    (cx, int(self.viewport_height * 0.25), "up"),
                    (cx, int(self.viewport_height * 0.75), "down"),
                ):
                    page.mouse.move(cx, cy)
                    page.mouse.down()
                    mark("pointer_down:center")
                    page.mouse.move(x, y, steps=6)
                    mark(f"drag:{label}")
                    page.mouse.up()
                    mark(f"pointer_up:{label}")
                    page.wait_for_timeout(self.sample_interval_ms)
                    sample()
            else:
                raise ValueError(f"unknown play policy: {policy}")

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
