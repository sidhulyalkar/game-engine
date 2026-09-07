import json
from pathlib import Path

from game_engine.repair_cycle import (
    _behavioral_child_gate,
    _staged_child_gate,
    _staged_failure_status,
)


class FakeFunnel:
    response = {}
    calls = []

    def __init__(self, install_browsers, timeout_ms, sample_interval_ms):
        FakeFunnel.calls.append({
            "install_browsers": install_browsers,
            "timeout_ms": timeout_ms,
            "sample_interval_ms": sample_interval_ms,
        })

    def run(self, builds_root, output_dir, browsers):
        FakeFunnel.calls[-1].update({
            "builds_root": str(builds_root),
            "output_dir": str(output_dir),
            "browsers": list(browsers),
        })
        output_dir.mkdir(parents=True, exist_ok=True)
        return dict(FakeFunnel.response)


def test_structured_repair_gate_delegates_to_staged_funnel(tmp_path):
    FakeFunnel.calls = []
    FakeFunnel.response = {
        "status": "qualified",
        "semantic_qualified_build_ids": ["child"],
        "semantic_blocked_build_ids": [],
        "reference_browser_build_ids": ["child"],
        "behaviorally_qualified_build_ids": ["child"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "behavioral_probe_errors": {},
        "cross_browser_build_ids": ["child"],
        "critic_reality_root": str(tmp_path / "critic-reality"),
    }

    gate = _staged_child_gate(
        tmp_path / "repairs",
        tmp_path / "cycle",
        ["chromium", "firefox", "webkit"],
        9000,
        funnel_factory=FakeFunnel,
    )

    assert gate["policy"] == "structured-staged-evidence"
    assert gate["qualified_build_ids"] == ["child"]
    assert gate["behaviorally_qualified_build_ids"] == ["child"]
    assert gate["critic_reality_root"].endswith("critic-reality")
    assert FakeFunnel.calls == [{
        "install_browsers": False,
        "timeout_ms": 9000,
        "sample_interval_ms": 160,
        "builds_root": str(tmp_path / "repairs"),
        "output_dir": str(tmp_path / "cycle" / "staged-evidence"),
        "browsers": ["chromium", "firefox", "webkit"],
    }]


def test_staged_failure_classification_preserves_failure_layer():
    assert _staged_failure_status({"status": "semantic_falsification_failed"}) == "children_failed_semantics"
    assert _staged_failure_status({"status": "reference_browser_failed"}) == "children_failed_reference_browser"
    assert _staged_failure_status({"status": "behavioral_evidence_incomplete"}) == "child_behavior_evidence_incomplete"
    assert _staged_failure_status({"status": "behavioral_repair_required"}) == "children_failed_behavior"
    assert _staged_failure_status({"status": "behavioral_failure"}) == "children_failed_behavior"
    assert _staged_failure_status({"status": "cross_browser_failed"}) == "children_failed_browser"
    assert _staged_failure_status({"status": "something-new"}) == "child_evidence_failed"


def test_semantic_failure_has_no_child_critic_reality(tmp_path):
    FakeFunnel.calls = []
    FakeFunnel.response = {
        "status": "semantic_falsification_failed",
        "semantic_qualified_build_ids": [],
        "semantic_blocked_build_ids": ["child"],
        "reference_browser_build_ids": [],
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "behavioral_probe_errors": {},
        "cross_browser_build_ids": [],
        "critic_reality_root": None,
    }
    gate = _staged_child_gate(
        tmp_path / "repairs", tmp_path / "cycle", ["chromium", "firefox"], 12000,
        funnel_factory=FakeFunnel,
    )
    assert gate["qualified_build_ids"] == []
    assert gate["critic_reality_root"] is None
    assert _staged_failure_status(gate) == "children_failed_semantics"


def test_legacy_child_is_explicitly_browser_only_not_strict_m4(tmp_path):
    repair_root = tmp_path / "repairs"
    repair_root.mkdir()
    (repair_root / "game-spec.json").write_text(json.dumps({"title": "legacy", "actions": []}))
    reality_root = tmp_path / "reality"
    reality_root.mkdir()
    (reality_root / "qualification.json").write_text(json.dumps({
        "full_pass_build_ids": ["legacy-child"]
    }))

    gate = _behavioral_child_gate(repair_root, reality_root, tmp_path / "cycle")
    assert gate["applied"] is False
    assert gate["policy"] == "legacy-browser-only"
    assert gate["qualified_build_ids"] == ["legacy-child"]
    assert "authoritative M4 not claimed" in gate["reason"]
    assert gate["critic_reality_root"] == str(reality_root)
