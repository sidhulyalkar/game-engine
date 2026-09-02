import json

from game_engine.autonomous import (
    TournamentPaths,
    _audit_builds_root,
    _audit_field,
    _behavioral_field,
    _critic_lineage,
    _critic_ready_field,
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


def test_repaired_behavioral_lineage_replaces_blocked_original_for_critics_and_later_repair(tmp_path):
    paths = TournamentPaths(tmp_path)
    original_behavior = paths.child("behavior-a") / "critic-reality"
    repaired_behavior = paths.child("behavior-repair-evidence-a") / "critic-reality"
    write_json(original_behavior / "qualification.json", {
        "full_pass_build_ids": [],
        "behavioral_gate_applied": True,
    })
    write_json(repaired_behavior / "qualification.json", {
        "full_pass_build_ids": ["fixed-child"],
        "behavioral_gate_applied": True,
    })

    builds_root, reality_root, lineage = _critic_lineage(paths, "a")
    assert builds_root == paths.child("behavior-repairs-a")
    assert reality_root == repaired_behavior
    assert lineage == "behavioral-repair"
    assert _audit_builds_root(paths, "a") == paths.child("behavior-repairs-a")
    ready, lineages = _critic_ready_field(paths)
    assert ready == [("a", "fixed-child")]
    assert lineages == {"a": "behavioral-repair"}


def test_original_behavioral_survivor_prevents_unnecessary_repair_lineage_selection(tmp_path):
    paths = TournamentPaths(tmp_path)
    write_json(paths.child("behavior-a") / "critic-reality" / "qualification.json", {
        "full_pass_build_ids": ["original-good"],
    })
    write_json(paths.child("behavior-repair-evidence-a") / "critic-reality" / "qualification.json", {
        "full_pass_build_ids": ["repair-child"],
    })
    builds_root, reality_root, lineage = _critic_lineage(paths, "a")
    assert builds_root == paths.child("builds-a")
    assert reality_root == paths.child("behavior-a") / "critic-reality"
    assert lineage == "original"


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


def test_audit_field_accepts_repaired_child_and_rejects_blocked_parent(tmp_path):
    paths = TournamentPaths(tmp_path)
    write_json(paths.child("behavior-a") / "critic-reality" / "qualification.json", {
        "full_pass_build_ids": [],
    })
    write_json(paths.child("behavior-repair-evidence-a") / "critic-reality" / "qualification.json", {
        "full_pass_build_ids": ["fixed-child"],
    })
    write_json(paths.child("audit-a") / "audit-summary.json", {
        "ranking": [
            {"build_id": "fixed-child", "critic_count": 2, "status": "advance"},
            {"build_id": "blocked-parent", "critic_count": 3, "status": "advance"},
        ],
    })
    qualified, matrix = _audit_field(paths)
    assert qualified == [("a", {"build_id": "fixed-child", "critic_count": 2, "status": "advance"})]
    assert matrix["a"] == [{"build_id": "fixed-child", "critic_count": 2, "status": "advance"}]


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
