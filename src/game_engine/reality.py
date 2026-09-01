from __future__ import annotations

import hashlib
import json
import math
import statistics
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class RealityResult:
    build_id: str
    provider: str
    browser: str
    ok: bool
    startup_ms: float | None
    reload_ms: float | None
    frame_median_ms: float | None
    frame_p95_ms: float | None
    body_width: int | None
    body_height: int | None
    canvas_count: int
    canvas_nonblank: bool
    visual_change: bool
    initial_screenshot: str | None
    after_input_screenshot: str | None
    input_trace: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def serve_directory(root: Path):
    handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(root), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def frame_stats(samples: Iterable[float]) -> tuple[float | None, float | None]:
    values = [float(v) for v in samples if 0 < float(v) < 1000]
    if not values:
        return None, None
    return statistics.median(values), _percentile(values, 0.95)


def _resolve_source_dir(builds_root: Path, source: str) -> Path:
    path = Path(source)
    if path.exists():
        return path
    candidate = builds_root / path.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"prototype source directory not found: {source}")


def discover_builds(builds_root: Path) -> list[dict]:
    payload = json.loads((builds_root / "builds.json").read_text())
    builds = []
    for entry in payload:
        if not entry.get("ok") or not entry.get("source_dir"):
            continue
        item = dict(entry)
        item["resolved_source_dir"] = str(_resolve_source_dir(builds_root, entry["source_dir"]))
        builds.append(item)
    return builds


def summarize_results(results: list[RealityResult], browsers: list[str]) -> dict:
    by_build: dict[str, list[RealityResult]] = {}
    for result in results:
        by_build.setdefault(result.build_id, []).append(result)
    full_pass = []
    matrix = {}
    expected = set(browsers)
    for build_id, rows in by_build.items():
        matrix[build_id] = {row.browser: row.ok for row in rows}
        passed = {row.browser for row in rows if row.ok}
        if expected and expected.issubset(passed):
            full_pass.append(build_id)
    return {
        "browsers": browsers,
        "builds_tested": len(by_build),
        "browser_checks": len(results),
        "successful_browser_checks": sum(r.ok for r in results),
        "full_pass_build_ids": sorted(full_pass),
        "matrix": matrix,
    }


_SNAPSHOT_JS = r"""() => {
  const canvases = [...document.querySelectorAll('canvas')];
  const canvasInfo = canvases.map(c => {
    const rect = c.getBoundingClientRect();
    let nonblank = null;
    let unique = null;
    try {
      const ctx = c.getContext('2d');
      if (ctx && c.width && c.height) {
        const sx = Math.max(1, Math.floor(c.width / 12));
        const sy = Math.max(1, Math.floor(c.height / 8));
        const colors = new Set();
        let energy = 0;
        for (let y = Math.floor(sy / 2); y < c.height; y += sy) {
          for (let x = Math.floor(sx / 2); x < c.width; x += sx) {
            const d = ctx.getImageData(x, y, 1, 1).data;
            energy += d[0] + d[1] + d[2] + d[3];
            colors.add(`${d[0]},${d[1]},${d[2]},${d[3]}`);
          }
        }
        unique = colors.size;
        nonblank = energy > 0 && colors.size > 1;
      }
    } catch (_) {}
    return {width:c.width,height:c.height,rectWidth:rect.width,rectHeight:rect.height,nonblank,unique};
  });
  const body = document.body?.getBoundingClientRect();
  return {
    title: document.title,
    bodyWidth: Math.round(body?.width || 0),
    bodyHeight: Math.round(body?.height || 0),
    canvasInfo,
    text: (document.body?.innerText || '').trim().slice(0, 1000),
  };
}"""

_FRAME_JS = r"""() => new Promise(resolve => {
  const deltas = [];
  let previous = null;
  function tick(now) {
    if (previous !== null) deltas.push(now - previous);
    previous = now;
    if (deltas.length >= 45) resolve(deltas);
    else requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})"""


class BrowserRealityLab:
    def __init__(self, browsers: Iterable[str] = ("chromium", "firefox", "webkit"), timeout_ms: int = 10_000, viewport_width: int = 1280, viewport_height: int = 720):
        self.browsers = [b.strip() for b in browsers if b.strip()]
        self.timeout_ms = timeout_ms
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def run(self, builds_root: Path, output_dir: Path) -> dict:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Browser Reality Lab requires Playwright. Install with `pip install playwright` and `python -m playwright install chromium firefox webkit`.") from exc
        builds = discover_builds(builds_root)
        if not builds:
            raise ValueError(f"no byte-qualified builds found in {builds_root}")
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[RealityResult] = []
        with sync_playwright() as playwright:
            for build in builds:
                source_dir = Path(build["resolved_source_dir"])
                with serve_directory(source_dir) as url:
                    for browser_name in self.browsers:
                        results.append(self._run_one(playwright, browser_name, build, url, output_dir))
                        self._write_results(output_dir, results)
        summary = summarize_results(results, self.browsers)
        (output_dir / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def _write_results(self, output_dir: Path, results: list[RealityResult]) -> None:
        payload = [asdict(result) for result in results]
        (output_dir / "reality.json").write_text(json.dumps(payload, indent=2) + "\n")
        (output_dir / "reality.jsonl").write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in payload))

    def _run_one(self, playwright, browser_name: str, build: dict, url: str, output_dir: Path) -> RealityResult:
        errors: list[str] = []
        warnings: list[str] = []
        input_trace: list[str] = []
        initial_path = after_path = None
        startup_ms = reload_ms = frame_median = frame_p95 = None
        body_width = body_height = None
        canvas_count = 0
        canvas_nonblank = visual_change = False
        browser = None
        try:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=True)
            context = browser.new_context(viewport={"width": self.viewport_width, "height": self.viewport_height})
            page = context.new_page()
            page.on("console", lambda msg: errors.append(f"console:{msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append(f"pageerror:{exc}"))
            started = time.perf_counter()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(500)
            startup_ms = (time.perf_counter() - started) * 1000
            snapshot_before = page.evaluate(_SNAPSHOT_JS)
            body_width = int(snapshot_before.get("bodyWidth") or 0)
            body_height = int(snapshot_before.get("bodyHeight") or 0)
            canvas_count = len(snapshot_before.get("canvasInfo") or [])
            canvas_nonblank = any(info.get("nonblank") is True for info in snapshot_before.get("canvasInfo") or [])
            shot_dir = output_dir / build["build_id"] / browser_name
            shot_dir.mkdir(parents=True, exist_ok=True)
            initial_file = shot_dir / "initial.png"
            after_file = shot_dir / "after-input.png"
            initial_bytes = page.screenshot(path=str(initial_file), full_page=True)
            initial_path = str(initial_file)
            cx, cy = self.viewport_width // 2, self.viewport_height // 2
            page.mouse.click(cx, cy)
            input_trace.append("click:center")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(int(self.viewport_width * 0.78), cy, steps=8)
            page.mouse.move(int(self.viewport_width * 0.22), cy, steps=8)
            page.mouse.up()
            input_trace.append("drag:center->right->left")
            for key in ("Space", "ArrowLeft", "ArrowRight", "w", "a", "s", "d"):
                page.keyboard.press(key)
                input_trace.append(f"key:{key}")
            page.wait_for_timeout(700)
            snapshot_after = page.evaluate(_SNAPSHOT_JS)
            canvas_nonblank = canvas_nonblank or any(info.get("nonblank") is True for info in snapshot_after.get("canvasInfo") or [])
            after_bytes = page.screenshot(path=str(after_file), full_page=True)
            after_path = str(after_file)
            visual_change = hashlib.sha256(initial_bytes).digest() != hashlib.sha256(after_bytes).digest()
            frames = page.evaluate(_FRAME_JS)
            frame_median, frame_p95 = frame_stats(frames)
            reload_started = time.perf_counter()
            page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(250)
            reload_ms = (time.perf_counter() - reload_started) * 1000
            if body_width < 100 or body_height < 100:
                errors.append(f"render surface too small: {body_width}x{body_height}")
            if canvas_count and not canvas_nonblank:
                errors.append("canvas appears blank across sampled pixels")
            if not canvas_count and not snapshot_after.get("text"):
                errors.append("no canvas and no visible text detected")
            if not visual_change:
                warnings.append("deterministic input/animation window produced no screenshot change")
            if startup_ms > 8000:
                errors.append(f"startup latency too high: {startup_ms:.0f}ms")
            if reload_ms > 8000:
                errors.append(f"reload latency too high: {reload_ms:.0f}ms")
            if frame_p95 is None:
                errors.append("could not measure requestAnimationFrame timing")
            elif frame_p95 > 80:
                errors.append(f"frame p95 too high: {frame_p95:.1f}ms")
            elif frame_p95 > 33:
                warnings.append(f"frame p95 is marginal: {frame_p95:.1f}ms")
            context.close()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
        return RealityResult(build_id=build["build_id"], provider=build.get("provider", "unknown"), browser=browser_name, ok=not errors, startup_ms=round(startup_ms, 2) if startup_ms is not None else None, reload_ms=round(reload_ms, 2) if reload_ms is not None else None, frame_median_ms=round(frame_median, 3) if frame_median is not None else None, frame_p95_ms=round(frame_p95, 3) if frame_p95 is not None else None, body_width=body_width, body_height=body_height, canvas_count=canvas_count, canvas_nonblank=canvas_nonblank, visual_change=visual_change, initial_screenshot=initial_path, after_input_screenshot=after_path, input_trace=input_trace, errors=errors, warnings=warnings)
