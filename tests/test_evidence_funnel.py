import json
from pathlib import Path

import pytest

from game_engine.evidence_funnel import plan_browser_stages, write_build_view
from game_engine.reality import discover_builds


def test_browser_plan_prefers_chromium_and_defers_other_engines():
    plan = plan_browser_stages(("firefox", "chromium", "webkit", "firefox"))
    assert plan.reference_browser == "chromium"
    assert plan.promotion_browsers == ("firefox", "webkit")
    assert plan.final_browsers == ("firefox", "chromium", "webkit")


def test_browser_plan_falls_back_to_first_requested_engine():
    plan = plan_browser_stages(("webkit", "firefox"))
    assert plan.reference_browser == "webkit"
    assert plan.promotion_browsers == ("firefox",)
    assert plan.final_browsers == ("webkit", "firefox")


def test_browser_plan_requires_an_engine():
    with pytest.raises(ValueError, match="at least one browser"):
        plan_browser_stages(())


def test_promotion_view_is_self_contained_and_contains_only_allowed_builds(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for build_id in ("keep", "drop"):
        game = source / f"game-{build_id}"
        game.mkdir()
        (game / "index.html").write_text(f"<html><body>{build_id}</body></html>")
    (source / "game-spec.json").write_text(json.dumps({"actions": [{"id": "primary"}]}))
    (source / "builds.json").write_text(json.dumps([
        {"build_id": "keep", "provider": "a", "ok": True, "source_dir": str(source / "game-keep"), "compressed_bytes": 10},
        {"build_id": "drop", "provider": "b", "ok": True, "source_dir": str(source / "game-drop"), "compressed_bytes": 11},
    ]))

    view = tmp_path / "promotion"
    manifest = write_build_view(source, view, ["keep"])
    assert manifest["allowed_build_ids"] == ["keep"]
    assert manifest["build_count"] == 1
    assert json.loads((view / "game-spec.json").read_text()) == {"actions": [{"id": "primary"}]}

    builds = discover_builds(view)
    assert [row["build_id"] for row in builds] == ["keep"]
    copied = Path(builds[0]["resolved_source_dir"])
    assert copied.is_relative_to(view)
    assert (copied / "index.html").read_text() == "<html><body>keep</body></html>"
    assert not any(path.name == "drop" for path in (view / "sources").iterdir())


def test_promotion_view_fails_closed_on_unknown_build_id(tmp_path):
    source = Path("tests/game_corpus/restart-good")
    with pytest.raises(ValueError, match="not present"):
        write_build_view(source, tmp_path / "view", ["not-a-build"])


def test_promotion_view_fails_closed_without_gamespec(tmp_path):
    source = tmp_path / "source"
    game = source / "game"
    game.mkdir(parents=True)
    (game / "index.html").write_text("<html></html>")
    (source / "builds.json").write_text(json.dumps([
        {"build_id": "a", "provider": "fixture", "ok": True, "source_dir": str(game)}
    ]))
    with pytest.raises(ValueError, match="missing GameSpec"):
        write_build_view(source, tmp_path / "view", ["a"])
