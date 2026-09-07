import json
from pathlib import Path

import game_engine.repair_cycle as repair_cycle
from game_engine.repair_cycle import _behavioral_child_gate


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_structured_repair_child_must_pass_evidence_broker_before_critics(tmp_path, monkeypatch):
    repair_root = tmp_path / "repairs"
    reality_root = tmp_path / "reality"
    output_dir = tmp_path / "cycle"
    write_json(repair_root / "game-spec.json", {
        "actions": [{"id": "primary", "kind": "key", "bindings": ["Space"], "required": True}]
    })
    write_json(reality_root / "qualification.json", {"full_pass_build_ids": ["child-a", "child-b"]})

    calls = []

    class FakeBroker:
        def __init__(self, browsers, sample_interval_ms):
            calls.append((tuple(browsers), sample_interval_ms))

        def run(self, builds_root, behavior_root, browser_reality_root):
            assert builds_root == repair_root
            assert browser_reality_root == reality_root
            critic_root = behavior_root / "critic-reality"
            write_json(critic_root / "qualification.json", {"full_pass_build_ids": ["child-a"]})
            return {
                "behaviorally_qualified_build_ids": ["child-a"],
                "behavioral_repair_build_ids": ["child-b"],
                "insufficient_evidence_build_ids": [],
                "probe_errors": {},
            }

    monkeypatch.setattr(repair_cycle, "EvidenceBroker", FakeBroker)
    result = _behavioral_child_gate(repair_root, reality_root, output_dir)
    assert result["applied"] is True
    assert result["qualified_build_ids"] == ["child-a"]
    assert result["repair_build_ids"] == ["child-b"]
    assert Path(result["critic_reality_root"]) == output_dir / "behavior" / "critic-reality"
    assert calls == [(('chromium',), 160)]


def test_legacy_repair_lineage_is_explicitly_marked_as_not_behaviorally_gated(tmp_path, monkeypatch):
    repair_root = tmp_path / "repairs"
    reality_root = tmp_path / "reality"
    write_json(repair_root / "game-spec.json", {"spec_version": "0.1"})
    write_json(reality_root / "qualification.json", {"full_pass_build_ids": ["legacy-child"]})

    class ForbiddenBroker:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy lineage should not pretend to have structured M4 evidence")

    monkeypatch.setattr(repair_cycle, "EvidenceBroker", ForbiddenBroker)
    result = _behavioral_child_gate(repair_root, reality_root, tmp_path / "cycle")
    assert result == {
        "applied": False,
        "reason": "legacy GameSpec has no structured actions",
        "qualified_build_ids": ["legacy-child"],
        "repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
        "critic_reality_root": str(reality_root),
    }


def test_structured_probe_gap_never_falls_back_to_unfiltered_browser_reality(tmp_path, monkeypatch):
    repair_root = tmp_path / "repairs"
    reality_root = tmp_path / "reality"
    output_dir = tmp_path / "cycle"
    write_json(repair_root / "game-spec.json", {
        "actions": [{"id": "primary", "kind": "key", "bindings": ["Space"], "required": True}]
    })
    write_json(reality_root / "qualification.json", {"full_pass_build_ids": ["child"]})

    class GapBroker:
        def __init__(self, **kwargs):
            pass

        def run(self, builds_root, behavior_root, browser_reality_root):
            critic_root = behavior_root / "critic-reality"
            write_json(critic_root / "qualification.json", {"full_pass_build_ids": []})
            return {
                "behaviorally_qualified_build_ids": [],
                "behavioral_repair_build_ids": [],
                "insufficient_evidence_build_ids": ["child"],
                "probe_errors": {"restart": "TimeoutError"},
            }

    monkeypatch.setattr(repair_cycle, "EvidenceBroker", GapBroker)
    result = _behavioral_child_gate(repair_root, reality_root, output_dir)
    assert result["applied"] is True
    assert result["qualified_build_ids"] == []
    assert result["insufficient_evidence_build_ids"] == ["child"]
    assert result["probe_errors"] == {"restart": "TimeoutError"}
    assert Path(result["critic_reality_root"]) != reality_root
