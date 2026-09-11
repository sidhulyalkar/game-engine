import json
from pathlib import Path

from game_engine.reality import RealityResult, discover_builds, frame_stats, summarize_results
from game_engine.render_evidence import assess_render_surface, normalize_visible_text


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
    def row(build, browser, ok, text="Score: 1"):
        return RealityResult(
            build, "p", browser, ok, 10, 10, 16, 18, 800, 600, 1, True, True,
            None, None, text, text,
        )

    results = [
        row("a", "chromium", True), row("a", "firefox", True), row("a", "webkit", True),
        row("b", "chromium", True), row("b", "firefox", False), row("b", "webkit", True),
    ]
    summary = summarize_results(results, ["chromium", "firefox", "webkit"])
    assert summary["full_pass_build_ids"] == ["a"]
    assert summary["successful_browser_checks"] == 5
    assert summary["semantic_divergence_build_ids"] == []


def test_sparse_canvas_with_visible_dynamic_evidence_is_not_false_failure():
    errors, warnings = assess_render_surface(
        canvas_count=1,
        canvas_nonblank=False,
        visual_change=True,
        initial_text="Score: 0",
        after_text="Score: 7",
    )
    assert errors == []
    assert warnings


def test_truly_dead_canvas_fails_reality_gate():
    errors, warnings = assess_render_surface(
        canvas_count=1,
        canvas_nonblank=False,
        visual_change=False,
        initial_text="",
        after_text="",
    )
    assert errors == ["canvas appears blank and page produced no other visible/dynamic evidence"]
    assert warnings == []


def test_summary_surfaces_cross_browser_semantic_divergence():
    def row(browser, text):
        return RealityResult(
            "a", "p", browser, True, 10, 10, 16, 18, 800, 600, 1, True, True,
            None, None, text, text,
        )

    results = [
        row("chromium", "Score: 0 Snap! Tap to restart"),
        row("firefox", "Score: 0 Snap! Tap to restart"),
        row("webkit", "Score: 7"),
    ]
    summary = summarize_results(results, ["chromium", "firefox", "webkit"])
    assert summary["full_pass_build_ids"] == ["a"]
    assert summary["semantic_divergence_build_ids"] == ["a"]


def test_visible_text_normalization_ignores_score_numbers_but_not_game_state():
    assert normalize_visible_text("Score: 7") == normalize_visible_text("Score: 123")
    assert normalize_visible_text("Score: 7") != normalize_visible_text("Score: 0 Snap! Tap to restart")
