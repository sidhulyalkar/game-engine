import json

from game_engine.schema import Brief, Concept
from game_engine.selection import write_joint_selection


def concept(cid, title, mechanic, controls, tags):
    return Concept(
        concept_id=cid,
        title=title,
        hook=f"{title}: {mechanic}",
        core_mechanic=mechanic,
        player_goal="Master the mechanic.",
        controls=controls,
        core_loop=["act", "react", "repeat"],
        escalation=["pressure rises"],
        visual_grammar="rainbow primitives",
        audio_grammar="procedural oscillator",
        category_fit=["desktop"],
        byte_hypothesis="compact Canvas state",
        tags=[*tags, "provider:fixture", "role:wild_inventor"],
    )


def write_leaderboard(path, concepts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {
            "rank": index + 1,
            "concept": item.to_dict(),
            "scorecard": {"total": 8.0 - index * 0.1},
        }
        for index, item in enumerate(concepts)
    ]))


def test_joint_selection_emits_shadow_without_changing_authoritative_winner(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    concepts = [
        concept("tether", "Tension Trail", "Stretch a tether and release tension to dash.", "WASD and Space.", ["stretch", "dash"]),
        concept("herd", "Rainbow Stampede", "Steer a herd through territory gates.", "Arrow keys steer.", ["herd", "territory"]),
        concept("prism", "Prism Fold", "Reflect projectiles through folding prism walls.", "Mouse aims and clicks.", ["reflect", "projectile"]),
        concept("rail", "Rainbow Rail", "Grind rails and preserve momentum through jumps.", "Arrows and Space.", ["grind", "momentum"]),
    ]
    leaderboard = tmp_path / "leaderboard.json"
    write_leaderboard(leaderboard, concepts)
    out = tmp_path / "champion"

    selection = write_joint_selection(
        brief,
        {"primary": leaderboard},
        out,
        top_k_per_source=4,
    )

    winner = json.loads((out / "winner.json").read_text())
    persisted_selection = json.loads((out / "selection.json").read_text())
    portfolio = json.loads((out / "portfolio.shadow.json").read_text())
    plan = json.loads((out / "prototype-plan.shadow.json").read_text())

    assert winner["concept"]["concept_id"] == selection["concept_id"]
    assert persisted_selection["concept_id"] == selection["concept_id"]
    assert winner["selection"]["concept_id"] == selection["concept_id"]
    assert winner["selection"]["shadow_portfolio"] == selection["shadow_portfolio"]
    assert portfolio["build_authority"] is False
    assert portfolio["members"][0]["concept_id"] == selection["concept_id"]
    assert plan["build_authority"] is False
    assert plan["max_total_builder_calls"] == 4
    assert selection["shadow_portfolio"]["written"] is True
    assert selection["shadow_portfolio"]["build_authority"] is False
    assert selection["shadow_portfolio"]["routing_authority"] is False
