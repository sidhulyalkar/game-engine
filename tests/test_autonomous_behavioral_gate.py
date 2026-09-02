import json

from game_engine.autonomous import (
    TournamentPaths,
    _audit_field,
    _behavioral_field,
    _critic_reality_root,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_behavioral_field_preserves_qualified_repair_insufficient_and_probe_errors(tmp_path):
    paths = TournamentPaths(tmp_path)
    write_json(paths.child("behavior-a") / "evidence-broker.json", {
        "behaviorally_qualified_build_ids": ["good"],
        "behavioral_repair_build_ids": ["dead-control"],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
        "decisions": [
            {"build_id": "good", "status": "behaviorally_qualified"},
            {"build_id": "dead-control", "status": "behavioral_repair"},
        ],
    })
    write_json(paths.child("behavior-b") / "evidence-broker.json", {
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": ["probe-gap"],
        "probe_errors": {"restart": "TimeoutError: browser probe stalled"},
        "decisions": [{"build_id": "probe-gap", "status": "insufficient_evidence"}],
    })

    qualified, repair, insufficient, matrix, errors = _behavioral_field(paths)
    assert qualified == [("a", "good")]
    assert repair == ["a:dead-control"]
    assert insufficient == ["b:probe-gap"]
    assert matrix["a"][0]["build_id"] == "good"
    assert errors == {"b": {"restart": "TimeoutError: browser probe stalled"}}


def test_critic_reality_prefers_behavioral_filter_and_falls_back_for_legacy(tmp_path):
    paths = TournamentPaths(tmp_path)
    reality = paths.child("reality-a")
    behavior = paths.child("behavior-a") / "critic-reality"
    write_json(reality / "qualification.json", {"full_pass_build_ids": ["raw"]})
    assert _critic_reality_root(paths, "a") == reality

    write_json(behavior / "qualification.json", {"full_pass_build_ids": ["qualified"]})
    assert _critic_reality_root(paths, "a") == behavior


def test_audit_field_cannot_reintroduce_build_removed_by_behavioral_gate(tmp_path):
    paths = TournamentPaths(tmp_path)
    write_json(paths.child("reality-a") / "qualification.json", {
        "full_pass_build_ids": ["good", "dead-control"],
    })
    write_json(paths.child("behavior-a") / "critic-reality" / "qualification.json", {
        "full_pass_build_ids": ["good"],
        "behavioral_gate_applied": True,
    })
    write_json(paths.child("audit-a") / "audit-summary.json", {
        "ranking": [
            {"build_id": "good", "critic_count": 2, "status": "advance"},
            {"build_id": "dead-control", "critic_count": 3, "status": "advance"},
        ],
    })

    qualified, matrix = _audit_field(paths)
    assert qualified == [("a", {"build_id": "good", "critic_count": 2, "status": "advance"})]
    assert matrix["a"] == [{"build_id": "good", "critic_count": 2, "status": "advance"}]


def test_audit_field_keeps_legacy_browser_reality_compatibility(tmp_path):
    paths = TournamentPaths(tmp_path)
    write_json(paths.child("reality-a") / "qualification.json", {
        "full_pass_build_ids": ["legacy"],
    })
    write_json(paths.child("audit-a") / "audit-summary.json", {
        "ranking": [{"build_id": "legacy", "critic_count": 2, "status": "repair"}],
    })

    qualified, matrix = _audit_field(paths)
    assert qualified == [("a", {"build_id": "legacy", "critic_count": 2, "status": "repair"})]
    assert matrix["a"][0]["build_id"] == "legacy"
