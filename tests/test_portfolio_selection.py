import json

from game_engine.portfolio_selection import (
    concept_distance,
    concept_descriptors,
    concept_provenance,
    select_concept_portfolio,
)
from game_engine.schema import Brief, Concept


def concept(
    cid,
    title,
    mechanic,
    controls,
    *,
    tags=None,
    loop=None,
    source_provider="p",
    source_role="wild_inventor",
):
    return Concept(
        concept_id=cid,
        title=title,
        hook=f"{title}: {mechanic}",
        core_mechanic=mechanic,
        player_goal="Master the mechanic and survive.",
        controls=controls,
        core_loop=loop or ["act", "react", "repeat"],
        escalation=["faster pressure"],
        visual_grammar="readable rainbow shapes",
        audio_grammar="simple reactive oscillator",
        category_fit=["desktop"],
        byte_hypothesis="Canvas primitives and compact state.",
        tags=[*(tags or []), f"provider:{source_provider}", f"role:{source_role}"],
    )


def write_leaderboard(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {
            "rank": index + 1,
            "concept": item.to_dict(),
            "scorecard": {"total": score},
        }
        for index, (item, score) in enumerate(rows)
    ]))


def test_provenance_cannot_manufacture_mechanical_novelty():
    a = concept(
        "a",
        "Rainbow Tether",
        "Stretch a tether, store tension, and release it to strike targets.",
        "WASD to stretch; Space to release.",
        tags=["stretch", "tether"],
        source_provider="nemotron",
        source_role="gameplay_director",
    )
    b = concept(
        "b",
        "Rainbow Tether",
        "Stretch a tether, store tension, and release it to strike targets.",
        "WASD to stretch; Space to release.",
        tags=["stretch", "tether"],
        source_provider="kimi",
        source_role="competition_judge",
    )

    assert concept_provenance(a) != concept_provenance(b)
    assert concept_descriptors(a) == concept_descriptors(b)
    assert concept_distance(a, b) == 0.0


def test_forced_incumbent_remains_slot_one_but_distinct_hypotheses_fill_shadow_budget(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    incumbent = concept(
        "inc",
        "Tension Trail",
        "Stretch a rainbow tether and release stored tension into a directional dash.",
        "WASD to stretch; Space to release.",
        tags=["stretch", "dash"],
    )
    near_duplicate = concept(
        "dup",
        "Tether Dash",
        "Stretch a rainbow tether and release stored tension into a directional dash.",
        "WASD to stretch; Space to release.",
        tags=["stretch", "dash"],
        source_provider="other",
    )
    stampede = concept(
        "herd",
        "Rainbow Stampede",
        "Steer a herd through gates while painting territory and avoiding collisions.",
        "Arrow keys steer the herd.",
        tags=["herd", "territory", "steer"],
        loop=["steer", "route", "paint"],
    )
    prism = concept(
        "prism",
        "Prism Fold",
        "Aim and reflect projectiles through folding prism walls to clear targets.",
        "Mouse aims; click reflects.",
        tags=["reflect", "projectile", "aim"],
        loop=["aim", "reflect", "chain"],
    )
    rail = concept(
        "rail",
        "Rainbow Rail",
        "Grind curving rainbow rails, jump gaps, and preserve momentum through turns.",
        "Arrow keys steer; Space jumps.",
        tags=["grind", "rail", "momentum"],
        loop=["grind", "steer", "jump"],
    )

    leaderboard = tmp_path / "leaderboard.json"
    write_leaderboard(leaderboard, [
        (incumbent, 8.0),
        (near_duplicate, 7.99),
        (stampede, 7.8),
        (prism, 7.7),
        (rail, 7.6),
    ])

    portfolio = select_concept_portfolio(
        brief,
        {"primary": leaderboard},
        portfolio_size=4,
        top_k_per_source=5,
        min_distance=0.25,
        incumbent_concept_id="inc",
    )

    ids = [row["concept_id"] for row in portfolio["members"]]
    assert ids[0] == "inc"
    assert portfolio["members"][0]["is_incumbent"] is True
    assert "dup" not in ids
    assert len(ids) == 4
    assert set(ids[1:]).issubset({"herd", "prism", "rail"})
    assert all(row["nearest_prior_distance"] >= 0.25 for row in portfolio["members"][1:])
    assert portfolio["mode"] == "shadow"
    assert portfolio["build_authority"] is False
    assert "not gameplay evidence" in portfolio["descriptor_authority"]


def test_distance_constraint_relaxation_is_explicit_when_field_is_homogeneous(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows")
    rows = []
    for index in range(3):
        rows.append((concept(
            f"c{index}",
            f"Tether Variant {index}",
            "Stretch a tether and release tension to dash.",
            "WASD to stretch; Space to release.",
            tags=["stretch", "tether", "dash"],
            source_provider=f"p{index}",
        ), 8.0 - index * 0.01))
    leaderboard = tmp_path / "leaderboard.json"
    write_leaderboard(leaderboard, rows)

    portfolio = select_concept_portfolio(
        brief,
        {"primary": leaderboard},
        portfolio_size=3,
        min_distance=0.9,
        incumbent_concept_id="c0",
    )

    assert len(portfolio["members"]) == 3
    assert portfolio["distance_constraint_relaxed"] is True
