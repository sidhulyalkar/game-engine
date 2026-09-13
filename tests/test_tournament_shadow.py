import json

from game_engine.schema import Brief, Concept
from game_engine.tournament_shadow import analyze_tournament_shadow


def concept(cid, title, mechanic, controls, tags):
    return Concept(
        concept_id=cid,
        title=title,
        hook=f"{title}: {mechanic}",
        core_mechanic=mechanic,
        player_goal="Master the mechanic.",
        controls=controls,
        core_loop=["act", "react", "repeat"],
        escalation=["faster pressure"],
        visual_grammar="procedural rainbow geometry",
        audio_grammar="procedural oscillator cues",
        category_fit=["desktop"],
        byte_hypothesis="Canvas primitives.",
        tags=[*tags, "provider:fixture", "role:wild_inventor"],
    )


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def test_shadow_analysis_reports_discarded_hypotheses_and_provider_phases(tmp_path):
    run = tmp_path / "run"
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop")
    incumbent = concept(
        "inc", "Tension Trail",
        "Stretch a tether and release tension to dash.",
        "WASD to stretch; Space to release.",
        ["stretch", "tether", "dash"],
    )
    herd = concept(
        "herd", "Rainbow Stampede",
        "Steer a herd through gates and paint territory.",
        "Arrow keys steer.",
        ["herd", "territory", "steer"],
    )
    prism = concept(
        "prism", "Prism Fold",
        "Aim and reflect projectiles through folding walls.",
        "Mouse aims; click reflects.",
        ["reflect", "projectile", "aim"],
    )

    write_json(run / "swarm-primary" / "leaderboard.json", [
        {"rank": 1, "concept": incumbent.to_dict(), "scorecard": {"total": 8.0}},
        {"rank": 2, "concept": herd.to_dict(), "scorecard": {"total": 7.8}},
        {"rank": 3, "concept": prism.to_dict(), "scorecard": {"total": 7.7}},
    ])
    write_json(run / "swarm-primary" / "contributions.json", [
        {
            "provider": "fixture-provider",
            "model": "fixture-model",
            "role": "wild_inventor",
            "ok": True,
            "concept_ids": ["inc", "herd", "prism"],
            "skipped": False,
            "elapsed_seconds": 4.0,
        }
    ])
    write_json(run / "champion" / "winner.json", {
        "brief": brief.to_dict(),
        "concept": incumbent.to_dict(),
        "scorecard": {"total": 8.0},
    })
    write_json(run / "champion" / "selection.json", {
        "source": "primary",
        "score": 8.0,
        "concept_id": "inc",
        "title": "Tension Trail",
    })

    output = tmp_path / "shadow.json"
    report = analyze_tournament_shadow(
        run,
        output,
        portfolio_size=3,
        top_k_per_source=3,
        min_distance=0.2,
    )

    assert json.loads(output.read_text()) == report
    assert report["routing_authority"] is False
    assert report["build_authority"] is False
    assert report["incumbent"]["concept_id"] == "inc"
    assert report["portfolio"]["members"][0]["concept_id"] == "inc"
    assert report["discarded_hypothesis_count"] == 2
    assert {row["concept_id"] for row in report["discarded_high_value_hypotheses"]} == {"herd", "prism"}
    assert report["discarded_distance_summary"]["min_from_incumbent"] > 0
    provider = report["provider_performance"]["providers"]["fixture-provider"]
    assert provider["ideation"]["successes"] == 1
    assert provider["ideation"]["observed_call_seconds"] == 4.0


def test_shadow_analysis_fails_closed_without_paid_swarm_field(tmp_path):
    run = tmp_path / "run"
    brief = Brief(theme="x")
    incumbent = concept("inc", "Only", "Stretch a tether.", "Space releases.", ["stretch"])
    write_json(run / "champion" / "winner.json", {
        "brief": brief.to_dict(),
        "concept": incumbent.to_dict(),
        "scorecard": {"total": 1.0},
    })

    try:
        analyze_tournament_shadow(run)
    except ValueError as exc:
        assert "no swarm leaderboards" in str(exc)
    else:
        raise AssertionError("missing swarm evidence must fail closed")
