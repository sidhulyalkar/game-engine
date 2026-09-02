import json

from game_engine.portfolio_selection import concept_distance, select_concept_portfolio
from game_engine.schema import Brief, Concept


def concept(concept_id, title, core, controls, tags, loop=None):
    return Concept(
        concept_id=concept_id,
        title=title,
        hook=core,
        core_mechanic=core,
        player_goal="Survive and master the interaction.",
        controls=controls,
        core_loop=loop or ["Act", "Read feedback", "Take risk"],
        escalation=["Pressure increases", "Geometry tightens"],
        visual_grammar="Procedural canvas silhouettes with rainbow trails",
        audio_grammar="Procedural WebAudio feedback",
        category_fit=["desktop"],
        byte_hypothesis="Canvas primitives and generated audio",
        tags=tags,
    )


def leaderboard(path, concepts):
    rows = []
    for rank, item in enumerate(concepts, 1):
        rows.append({
            "rank": rank,
            "concept": item.to_dict(),
            "scorecard": {"total": 9.0 - rank * 0.1},
        })
    path.write_text(json.dumps(rows))


def test_portfolio_prefers_distinct_build_hypotheses_over_near_duplicates(tmp_path):
    orbit_a = concept(
        "orbit-a",
        "Aurora Orbit",
        "Steer a unicorn around a star, banking orbit momentum while dodging hazards.",
        "Mouse pointer steers the orbit; click dashes.",
        ["orbit", "momentum", "dodge"],
    )
    orbit_b = concept(
        "orbit-b",
        "Prism Orbit",
        "Steer a unicorn around a star, banking orbit momentum while dodging hazards.",
        "Mouse pointer steers the orbit; click dashes.",
        ["orbit", "momentum", "dodge"],
    )
    tether = concept(
        "tether",
        "Rainbow Slingshot",
        "Stretch a spring tether with WASD and release stored tension to slingshot through enemies.",
        "WASD stretches; Space releases the slingshot.",
        ["tether", "spring", "slingshot"],
    )
    paint = concept(
        "paint",
        "Herd Highway",
        "Paint rainbow routes that change territory and guide an autonomous unicorn herd.",
        "Drag the mouse to paint routes; click recalls the herd.",
        ["paint", "territory", "herd"],
    )
    rhythm = concept(
        "rhythm",
        "Prism Rail",
        "Grind rainbow rails and switch lanes on the beat to survive a rhythm race.",
        "Arrow keys switch rails; Space jumps on the beat.",
        ["rail", "grind", "rhythm"],
    )

    primary = tmp_path / "primary.json"
    rescue = tmp_path / "rescue.json"
    leaderboard(primary, [orbit_a, orbit_b, tether])
    leaderboard(rescue, [paint, rhythm])

    result = select_concept_portfolio(
        Brief(theme="Unicorns and Rainbows", primary_category="desktop"),
        {"primary": primary, "rescue": rescue},
        portfolio_size=4,
        top_k_per_source=5,
        min_distance=0.28,
        diversity_weight=0.55,
    )

    ids = [row["concept_id"] for row in result["members"]]
    assert result["portfolio_size_selected"] == 4
    assert result["distance_constraint_relaxed"] is False
    assert not ({"orbit-a", "orbit-b"} <= set(ids))
    selected = [Concept.from_dict(row["concept"]) for row in result["members"]]
    for index, a in enumerate(selected):
        for b in selected[index + 1:]:
            assert concept_distance(a, b) >= 0.28


def test_preprototype_portfolio_is_explicitly_not_a_quality_claim(tmp_path):
    a = concept("a", "A", "Orbit and dodge with momentum.", "Mouse steers.", ["orbit"])
    b = concept("b", "B", "Stretch a tether and release.", "WASD and Space.", ["tether"])
    path = tmp_path / "field.json"
    leaderboard(path, [a, b])
    result = select_concept_portfolio(
        Brief(theme="Unicorns and Rainbows", primary_category="desktop"),
        {"field": path},
        portfolio_size=2,
    )
    assert result["selection_role"] == "preprototype build-budget allocation only"
    assert result["portfolio_size_selected"] == 2
