import json
from types import SimpleNamespace

from game_engine.source_audit import SourceGameplayLab


class NeverCalledClient:
    name = "never-called"

    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        raise AssertionError("deterministically falsified builds must not spend an LLM critic call")


def test_deterministic_blocker_skips_all_source_critic_calls(tmp_path):
    builds = tmp_path / "builds"
    game = builds / "game"
    reality = tmp_path / "reality"
    out = tmp_path / "audit"
    game.mkdir(parents=True)
    reality.mkdir()

    (game / "index.html").write_text("<script>const x=Math.random()</script>")
    (builds / "builds.json").write_text(json.dumps([
        {
            "provider": "fixture-builder",
            "build_id": "bad",
            "ok": True,
            "source_dir": "game",
            "compressed_bytes": 100,
            "byte_headroom": 13212,
        }
    ]))
    (builds / "game-spec.json").write_text(json.dumps({
        "timing_contract": {"deterministic_seed": True},
        "telemetry_contract": {"snapshot": ["score"], "events": []},
    }))
    (reality / "qualification.json").write_text(json.dumps({"full_pass_build_ids": ["bad"]}))
    (reality / "reality.json").write_text("[]")

    client = NeverCalledClient()
    lab = SourceGameplayLab([(SimpleNamespace(name="critic"), client)], max_workers=1)
    result = lab.run(None, None, builds, out, reality)

    assert client.calls == 0
    assert result["falsified_build_ids"] == ["bad"]
    assert result["llm_critic_eligible_build_ids"] == []
    assert result["reject_build_ids"] == ["bad"]
    assert result["ranking"][0]["evidence_source"] == "deterministic_source_falsification"
    details = json.loads((out / "audits.json").read_text())
    codes = {row["code"] for row in details[0]["deterministic_findings"]}
    assert "nondeterministic_rng" in codes
    assert "missing_telemetry_contract" in codes
