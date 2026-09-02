import json
from pathlib import Path

from game_engine.schema import Brief, Concept
from game_engine.selection import select_joint_finalist


def _concept(cid: str, title: str, mechanic: str) -> Concept:
    return Concept(
        concept_id=cid,
        title=title,
        hook=mechanic,
        core_mechanic=mechanic,
        player_goal="Score through escalating risk.",
        controls="WASD + Space",
        core_loop=["read", "commit", "recover"],
        escalation=["faster", "rule inversion"],
        visual_grammar="procedural rainbow geometry",
        audio_grammar="procedural timing tones",
        category_fit=["desktop"],
        byte_hypothesis="Canvas + WebAudio primitives",
        risks=[],
        tags=[],
    )


def _leaderboard(path: Path, concepts: list[Concept]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {
            "rank": index + 1,
            "concept": concept.to_dict(),
            "scorecard": {"total": 10.0 - index},
        }
        for index, concept in enumerate(concepts)
    ]))


def test_rescue_finalists_are_limited_to_successful_rescue_concept_ids(tmp_path: Path):
    brief = Brief(theme="Unicorns and Rainbows")
    primary = _concept(
        "primary-llm",
        "Prism Spring",
        "Spring tension turns movement timing into rainbow collision risk and scoring.",
    )
    deterministic_rescue_seed = _concept(
        "rescue-seed",
        "Procedural Decoy",
        "A deterministic seed that should remain prompt context rather than rescue evidence.",
    )
    generated_rescue = _concept(
        "rescue-generated",
        "Horn Brake",
        "Brake against rainbow momentum to redirect hazards into a scoring lane.",
    )

    primary_path = tmp_path / "primary" / "leaderboard.json"
    rescue_path = tmp_path / "rescue" / "leaderboard.json"
    _leaderboard(primary_path, [primary])
    _leaderboard(rescue_path, [deterministic_rescue_seed, generated_rescue])
    (rescue_path.parent / "contributions.json").write_text(json.dumps([
        {
            "provider": "kimi-rescue",
            "role": "gameplay_director",
            "ok": True,
            "concept_ids": ["rescue-generated"],
        }
    ]))

    result = select_joint_finalist(
        brief,
        {"primary": primary_path, "rescue": rescue_path},
        top_k_per_source=2,
    )

    ranked_ids = {row["concept_id"] for row in result["ranking"]}
    assert "rescue-seed" not in ranked_ids
    assert "rescue-generated" in ranked_ids
    assert result["source_candidate_counts"] == {"primary": 1, "rescue": 1}
    assert result["source_filtered_counts"]["rescue"] == 1


def test_legacy_rescue_source_without_contribution_sidecar_keeps_old_behavior(tmp_path: Path):
    brief = Brief(theme="Unicorns and Rainbows")
    rescue = _concept("legacy", "Legacy Rescue", "Rainbow timing creates risk and score.")
    path = tmp_path / "legacy" / "leaderboard.json"
    _leaderboard(path, [rescue])

    result = select_joint_finalist(brief, {"rescue": path}, top_k_per_source=1)
    assert result["concept"].concept_id == "legacy"
    assert result["source_candidate_counts"]["rescue"] == 1
