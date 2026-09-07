import json
from pathlib import Path

from game_engine.evidence_funnel import StagedEvidenceFunnel


class FakeReality:
    responses = []
    calls = []

    def __init__(self, browsers, timeout_ms):
        self.browsers = tuple(browsers)
        self.timeout_ms = timeout_ms

    def run(self, builds_root, output_dir):
        FakeReality.calls.append((self.browsers, Path(builds_root), Path(output_dir)))
        response = dict(FakeReality.responses.pop(0))
        output_dir.mkdir(parents=True, exist_ok=True)
        ids = [str(value) for value in response.get("full_pass_build_ids", [])]
        qualification = {
            "browsers": list(self.browsers),
            "full_pass_build_ids": ids,
            "matrix": {build_id: {browser: True for browser in self.browsers} for build_id in ids},
            "initial_text_matrix": {build_id: {browser: "fixture" for browser in self.browsers} for build_id in ids},
            **response,
        }
        (output_dir / "qualification.json").write_text(json.dumps(qualification))
        (output_dir / "reality.json").write_text(json.dumps([
            {"build_id": build_id, "browser": browser, "ok": True}
            for build_id in ids
            for browser in self.browsers
        ]))
        return qualification


class FakeBroker:
    response = {}
    calls = []

    def __init__(self, browsers, sample_interval_ms):
        self.browsers = tuple(browsers)
        self.sample_interval_ms = sample_interval_ms

    def run(self, builds_root, output_dir, reality_root):
        FakeBroker.calls.append((self.browsers, Path(builds_root), Path(output_dir), Path(reality_root)))
        output_dir.mkdir(parents=True, exist_ok=True)
        return dict(FakeBroker.response)


def reset_fakes():
    FakeReality.responses = []
    FakeReality.calls = []
    FakeBroker.response = {}
    FakeBroker.calls = []


def make_funnel(installs):
    return StagedEvidenceFunnel(
        install_browsers=True,
        installer=lambda engines: installs.append(tuple(engines)),
        reality_factory=FakeReality,
        broker_factory=FakeBroker,
    )


def test_exact_run64_semantic_failure_spends_zero_browser_budget(tmp_path):
    reset_fakes()
    installs = []
    result = make_funnel(installs).run(
        Path("tests/game_corpus/run64-tension-trail"),
        tmp_path / "funnel",
        ("chromium", "firefox", "webkit"),
    )
    assert result["status"] == "semantic_falsification_failed"
    assert result["semantic_qualified_build_ids"] == []
    assert result["semantic_blocked_build_ids"] == ["b97d9a0640"]
    assert installs == []
    assert FakeReality.calls == []
    assert FakeBroker.calls == []
    assert result["promotion_attempted"] is False


def test_behavioral_failure_never_installs_firefox_or_webkit(tmp_path):
    reset_fakes()
    installs = []
    FakeReality.responses = [{"full_pass_build_ids": ["restart-good"]}]
    FakeBroker.response = {
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": ["restart-good"],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
    }
    result = make_funnel(installs).run(
        Path("tests/game_corpus/restart-good"),
        tmp_path / "funnel",
        ("chromium", "firefox", "webkit"),
    )
    assert result["status"] == "behavioral_repair_required"
    assert result["semantic_qualified_build_ids"] == ["restart-good"]
    assert installs == [("chromium",)]
    assert len(FakeReality.calls) == 1
    assert result["promotion_attempted"] is False


def test_behavioral_probe_gap_never_purchases_promotion_browsers(tmp_path):
    reset_fakes()
    installs = []
    FakeReality.responses = [{"full_pass_build_ids": ["restart-good"]}]
    FakeBroker.response = {
        "behaviorally_qualified_build_ids": [],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": ["restart-good"],
        "probe_errors": {"restart": "TimeoutError"},
    }
    result = make_funnel(installs).run(
        Path("tests/game_corpus/restart-good"), tmp_path / "funnel",
        ("chromium", "firefox", "webkit"),
    )
    assert result["status"] == "behavioral_evidence_incomplete"
    assert installs == [("chromium",)]
    assert result["behavioral_probe_errors"] == {"restart": "TimeoutError"}


def test_reference_browser_failure_stops_before_behavior_and_promotion(tmp_path):
    reset_fakes()
    installs = []
    FakeReality.responses = [{"full_pass_build_ids": []}]
    result = make_funnel(installs).run(
        Path("tests/game_corpus/restart-good"), tmp_path / "funnel",
        ("chromium", "firefox", "webkit"),
    )
    assert result["status"] == "reference_browser_failed"
    assert installs == [("chromium",)]
    assert FakeBroker.calls == []


def test_only_behaviorally_qualified_builds_enter_full_browser_field(tmp_path):
    reset_fakes()
    installs = []
    source = tmp_path / "source"
    source.mkdir()
    for build_id in ("keep", "drop"):
        game = source / build_id
        game.mkdir()
        (game / "index.html").write_text(f"<html><body>{build_id}</body></html>")
    (source / "game-spec.json").write_text(json.dumps({"actions": [{"id": "primary"}]}))
    (source / "builds.json").write_text(json.dumps([
        {"build_id": "keep", "provider": "a", "ok": True, "source_dir": str(source / "keep")},
        {"build_id": "drop", "provider": "b", "ok": True, "source_dir": str(source / "drop")},
    ]))

    FakeReality.responses = [
        {"full_pass_build_ids": ["keep", "drop"]},
        {"full_pass_build_ids": ["keep"]},
    ]
    FakeBroker.response = {
        "behaviorally_qualified_build_ids": ["keep"],
        "behavioral_repair_build_ids": ["drop"],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
    }
    result = make_funnel(installs).run(
        source, tmp_path / "funnel", ("chromium", "firefox", "webkit")
    )
    assert result["status"] == "qualified"
    # Preserve the original build-field evidence order; filtering must not rewrite provenance.
    assert result["semantic_qualified_build_ids"] == ["keep", "drop"]
    assert installs == [("chromium",), ("firefox", "webkit")]
    assert [call[0] for call in FakeReality.calls] == [
        ("chromium",), ("chromium", "firefox", "webkit")
    ]
    promotion_builds = json.loads(
        (Path(result["promotion_view_root"]) / "builds.json").read_text()
    )
    assert [row["build_id"] for row in promotion_builds] == ["keep"]
    critic_q = json.loads(
        (Path(result["critic_reality_root"]) / "qualification.json").read_text()
    )
    assert critic_q["full_pass_build_ids"] == ["keep"]
    assert result["cross_browser_build_ids"] == ["keep"]


def test_cross_browser_failure_is_distinct_from_behavior_failure(tmp_path):
    reset_fakes()
    installs = []
    FakeReality.responses = [
        {"full_pass_build_ids": ["restart-good"]},
        {"full_pass_build_ids": []},
    ]
    FakeBroker.response = {
        "behaviorally_qualified_build_ids": ["restart-good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
    }
    result = make_funnel(installs).run(
        Path("tests/game_corpus/restart-good"), tmp_path / "funnel",
        ("chromium", "firefox", "webkit"),
    )
    assert result["status"] == "cross_browser_failed"
    assert installs == [("chromium",), ("firefox", "webkit")]
    assert result["behaviorally_qualified_build_ids"] == ["restart-good"]
    assert result["cross_browser_build_ids"] == []


def test_single_browser_qualification_reuses_reference_reality(tmp_path):
    reset_fakes()
    installs = []
    FakeReality.responses = [{"full_pass_build_ids": ["restart-good"]}]
    FakeBroker.response = {
        "behaviorally_qualified_build_ids": ["restart-good"],
        "behavioral_repair_build_ids": [],
        "insufficient_evidence_build_ids": [],
        "probe_errors": {},
    }
    result = make_funnel(installs).run(
        Path("tests/game_corpus/restart-good"),
        tmp_path / "funnel",
        ("chromium",),
    )
    assert result["status"] == "qualified"
    assert installs == [("chromium",)]
    assert len(FakeReality.calls) == 1
    assert result["promotion_attempted"] is False
    assert result["cross_browser_build_ids"] == ["restart-good"]
    assert result["final_reality_root"].endswith("reference-reality")
