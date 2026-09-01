import json

from game_engine.orchestrator import Studio
from game_engine.schema import Brief


def test_run_writes_reproducible_artifacts(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows", target_categories=["desktop"])
    manifest = Studio(seed=13).run(brief, tmp_path, count=10)
    assert manifest["winner_id"]
    leaderboard = json.loads((tmp_path / "leaderboard.json").read_text())
    assert leaderboard[0]["scorecard"]["total"] >= leaderboard[-1]["scorecard"]["total"]
    assert (tmp_path / "STUDIO_BRIEF.md").exists()
