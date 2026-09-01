import json
from pathlib import Path

from game_engine.reality import RealityResult, discover_builds, frame_stats, summarize_results


def test_frame_stats_are_robust():
    median, p95 = frame_stats([16, 17, 16, 18, 17, 5000, -1])
    assert median == 17
    assert 17 <= p95 <= 18


def test_discover_builds_finds_relative_artifact_path(tmp_path: Path):
    build = tmp_path / "nemotron-abc"
    build.mkdir()
    (build / "index.html").write_text("<html></html>")
    (tmp_path / "builds.json").write_text(json.dumps([
        {"provider": "n", "build_id": "abc", "ok": True, "source_dir": "runs/elsewhere/nemotron-abc"},
        {"provider": "x", "build_id": "bad", "ok": False, "source_dir": None},
    ]))
    rows = discover_builds(tmp_path)
    assert len(rows) == 1
    assert Path(rows[0]["resolved_source_dir"]) == build


def test_summary_requires_same_build_to_pass_every_browser():
    def row(build, browser, ok):
        return RealityResult(build, "p", browser, ok, 10, 10, 16, 18, 800, 600, 1, True, True, None, None)

    results = [
        row("a", "chromium", True), row("a", "firefox", True), row("a", "webkit", True),
        row("b", "chromium", True), row("b", "firefox", False), row("b", "webkit", True),
    ]
    summary = summarize_results(results, ["chromium", "firefox", "webkit"])
    assert summary["full_pass_build_ids"] == ["a"]
    assert summary["successful_browser_checks"] == 5
