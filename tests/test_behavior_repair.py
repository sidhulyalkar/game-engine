import json
from dataclasses import dataclass
from pathlib import Path

from game_engine.behavior_repair import BehavioralRepairForge, load_behavioral_repair_candidates
from game_engine.schema import Brief, Concept


@dataclass
class Spec:
    name: str


class HtmlClient:
    def __init__(self, html):
        self.html = html
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        assert "CAUSAL BROWSER EVIDENCE" in prompt
        assert "do not delete or rename a required control" in prompt
        assert "parallel fake state machine" in prompt
        return self.html


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def make_behavior_root(tmp_path):
    root = tmp_path / "behavior"
    write_json(root / "evidence-broker.json", {
        "decisions": [{
            "build_id": "restart-stale",
            "status": "behavioral_repair",
            "blockers": ["fresh-run restart contract failed"],
            "evidence_gaps": [],
        }],
        "behavioral_repair_build_ids": ["restart-stale"],
    })
    write_json(root / "action-causality" / "action-summary.json", {
        "builds": [{"build_id": "restart-stale", "qualified": True}],
    })
    write_json(root / "restart" / "restart-summary.json", {
        "cases": [{
            "build_id": "restart-stale",
            "ok": False,
            "violations": ["restart did not return state to fresh baseline"],
        }],
    })
    write_json(root / "agency" / "playtest-summary.json", {
        "builds": [{"build_id": "restart-stale", "mechanically_observable": True}],
        "independently_observable_build_ids": ["restart-stale"],
        "telemetry_visual_contradiction_build_ids": [],
    })
    return root


def concept():
    return Concept(
        concept_id="fixture",
        title="Fixture",
        hook="fixture",
        core_mechanic="press to mutate and restart",
        player_goal="mutate then restart",
        controls="Space, R",
        core_loop=["press", "restart"],
        escalation=["repeat"],
        visual_grammar="canvas",
        audio_grammar="bleep",
        category_fit=["desktop"],
        byte_hypothesis="tiny",
        risks=[],
        tags=[],
    )


def test_candidate_loader_attaches_exact_probe_evidence(tmp_path):
    behavior_root = make_behavior_root(tmp_path)
    builds_root = Path("tests/game_corpus/restart-stale")
    candidates = load_behavioral_repair_candidates(builds_root, behavior_root)
    assert len(candidates) == 1
    build, decision, evidence = candidates[0]
    assert build["build_id"] == "restart-stale"
    assert decision["status"] == "behavioral_repair"
    assert evidence["action_causality"][0]["qualified"] is True
    assert evidence["restart"][0]["ok"] is False
    assert evidence["agency_flags"]["independently_observable"] is True


def test_behavioral_repair_forge_packages_only_static_clean_child(tmp_path):
    behavior_root = make_behavior_root(tmp_path)
    builds_root = Path("tests/game_corpus/restart-stale")
    repaired_html = Path("tests/game_corpus/restart-good/game/index.html").read_text()
    client = HtmlClient(repaired_html)
    out = tmp_path / "repairs"

    results = BehavioralRepairForge([(Spec("fixture-repairer"), client)], max_workers=1).build(
        Brief(theme="Unicorns and Rainbows", primary_category="desktop"),
        concept(),
        builds_root,
        behavior_root,
        out,
        max_parents=1,
    )

    assert client.calls == 1
    assert len(results) == 1
    child = results[0]
    assert child.ok is True, child
    assert child.parent_build_id == "restart-stale"
    assert child.build_id != child.parent_build_id
    assert child.compressed_bytes is not None and child.compressed_bytes < 13 * 1024
    assert child.remaining_source_blockers == []
    assert Path(child.source_dir, "index.html").read_text() == repaired_html
    assert Path(child.zip_path).exists()
    assert (out / "game-spec.json").exists()
    manifest = json.loads((out / "behavior-repair-manifest.json").read_text())
    assert manifest["repair_candidates"] == 1
    assert manifest["attempted_children"] == 1
    assert manifest["successful_children"] == 1


def test_no_behavioral_repair_decision_spends_zero_model_calls(tmp_path):
    behavior_root = tmp_path / "behavior"
    write_json(behavior_root / "evidence-broker.json", {
        "decisions": [{"build_id": "restart-stale", "status": "behaviorally_qualified"}],
        "behavioral_repair_build_ids": [],
    })
    client = HtmlClient(Path("tests/game_corpus/restart-good/game/index.html").read_text())
    results = BehavioralRepairForge([(Spec("fixture-repairer"), client)], max_workers=1).build(
        Brief(theme="x", primary_category="desktop"),
        concept(),
        Path("tests/game_corpus/restart-stale"),
        behavior_root,
        tmp_path / "repairs",
    )
    assert results == []
    assert client.calls == 0
