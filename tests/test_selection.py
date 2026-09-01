import json
from pathlib import Path

from game_engine.schema import Brief, Concept
from game_engine.selection import select_joint_finalist, write_joint_selection


def concept(cid: str, title: str, mechanic: str, controls: str = "Space") -> Concept:
    return Concept(
        concept_id=cid,
        title=title,
        hook=mechanic,
        core_mechanic=mechanic,
        player_goal="Chase a score through escalating risk.",
        controls=controls,
        core_loop=["read", "commit", "recover"],
        escalation=["faster", "invert a known rule"],
        visual_grammar="procedural stained glass trails",
        audio_grammar="procedural WebAudio impacts",
        category_fit=["desktop"],
        byte_hypothesis="Canvas WebAudio seeded primitives",
        risks=[],
        tags=[],
    )


def leaderboard(path: Path, rows: list[tuple[Concept, float]]) -> None:
    path.write_text(json.dumps([
        {
            "rank": i + 1,
            "concept": c.to_dict(),
            "scorecard": {"total": original},
        }
        for i, (c, original) in enumerate(rows)
    ]))


def test_joint_selection_does_not_compare_incompatible_original_totals(tmp_path: Path):
    brief = Brief(theme="Unicorns and Rainbows")
    strong = concept(
        "strong",
        "Prism Spring",
        "Rainbow spring tension turns timing and position into a physical score multiplier with procedural collision risk.",
    )
    weak = concept("weak", "Plain Drift", "Move toward points.")
    primary = tmp_path / "primary.json"
    rescue = tmp_path / "rescue.json"
    leaderboard(primary, [(strong, 6.0)])
    leaderboard(rescue, [(weak, 9.9)])

    result = select_joint_finalist(brief, {"primary": primary, "rescue": rescue}, top_k_per_source=1)
    assert result["source"] == "primary"
    assert result["concept"].concept_id == "strong"
    assert result["original_score"] == 6.0


def test_joint_selection_writes_reproducible_champion_contract(tmp_path: Path):
    brief = Brief(theme="Unicorns and Rainbows")
    c = concept("one", "Horn Relay", "Rainbow collision timing stores momentum and risk.")
    source = tmp_path / "source.json"
    leaderboard(source, [(c, 7.1)])
    out = tmp_path / "champion"

    summary = write_joint_selection(brief, {"primary": source}, out, top_k_per_source=4)
    winner = json.loads((out / "winner.json").read_text())
    assert summary["score_scope"] == "joint-finalist-population"
    assert winner["concept"]["concept_id"] == "one"
    assert (out / "selection.json").exists()
