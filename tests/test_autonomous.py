import json

from game_engine.autonomous import StageJournal, TournamentPaths, _audit_field, _cross_browser_field


def test_stage_journal_persists_incrementally_and_failure_artifact(tmp_path):
    journal = StageJournal(tmp_path, seed=17)
    journal.record("primary", "degraded", successful_models=["a"])
    payload = json.loads((tmp_path / "stage-journal.json").read_text())
    assert payload["seed"] == 17
    assert payload["stages"][0]["stage"] == "primary"
    assert payload["stages"][0]["status"] == "degraded"
    assert payload["stages"][0]["successful_models"] == ["a"]

    journal.fail("final-health", "need a second model family")
    failure = json.loads((tmp_path / "failure.json").read_text())
    assert failure["stage"] == "final-health"
    assert "second model family" in failure["message"]


def test_stage_journal_accepts_health_payload_with_its_own_status(tmp_path):
    journal = StageJournal(tmp_path, seed=55)
    health = {
        "status": "degraded",
        "usable": True,
        "qualified": False,
        "successful_models": ["moonshotai/kimi-k3", "nvidia/nemotron-3-super-120b-a12b"],
        "missing_roles": ["gameplay_director", "competition_judge", "desktop_specialist"],
    }
    journal.record("primary-health", health["status"], **health)
    payload = json.loads((tmp_path / "stage-journal.json").read_text())
    row = payload["stages"][0]
    assert row["stage"] == "primary-health"
    assert row["status"] == "degraded"
    assert row["usable"] is True
    assert row["missing_roles"] == ["gameplay_director", "competition_judge", "desktop_specialist"]


def test_cross_browser_field_collects_only_full_pass_ids_and_divergence(tmp_path):
    paths = TournamentPaths(tmp_path)
    for race, payload in {
        "a": {
            "matrix": {"good-a": {"chromium": True, "firefox": True, "webkit": True}},
            "full_pass_build_ids": ["good-a"],
            "semantic_divergence_build_ids": ["good-a"],
        },
        "b": {
            "matrix": {"bad-b": {"chromium": True, "firefox": False, "webkit": True}},
            "full_pass_build_ids": [],
            "semantic_divergence_build_ids": [],
        },
    }.items():
        root = paths.child(f"reality-{race}")
        root.mkdir(parents=True)
        (root / "qualification.json").write_text(json.dumps(payload))

    full_pass, matrices, divergence = _cross_browser_field(paths)
    assert full_pass == [("a", "good-a")]
    assert matrices["a"]["good-a"]["webkit"] is True
    assert matrices["b"]["bad-b"]["firefox"] is False
    assert divergence == ["a:good-a"]


def test_audit_field_ignores_non_browser_survivors_and_requires_two_critics(tmp_path):
    paths = TournamentPaths(tmp_path)
    reality = paths.child("reality-a")
    audit = paths.child("audit-a")
    reality.mkdir(parents=True)
    audit.mkdir(parents=True)
    (reality / "qualification.json").write_text(json.dumps({"full_pass_build_ids": ["survivor"]}))
    (audit / "audit-summary.json").write_text(json.dumps({
        "ranking": [
            {"build_id": "survivor", "critic_count": 2, "status": "repair"},
            {"build_id": "not-browser-qualified", "critic_count": 3, "status": "advance"},
            {"build_id": "survivor", "critic_count": 1, "status": "advance"},
        ]
    }))

    qualified, matrix = _audit_field(paths)
    assert qualified == [("a", {"build_id": "survivor", "critic_count": 2, "status": "repair"})]
    assert len(matrix["a"]) == 2
    assert all(row["build_id"] == "survivor" for row in matrix["a"])
