from game_engine.repair_cycle import evidence_improved


def test_verdict_improvement_counts():
    improved, reasons = evidence_improved(
        {"status": "repair", "overall": 6.2, "blockers": 1},
        {"status": "advance", "overall": 7.1, "blockers": 0},
    )
    assert improved
    assert any("verdict improved" in reason for reason in reasons)


def test_score_improvement_counts_without_status_change():
    improved, reasons = evidence_improved(
        {"status": "repair", "overall": 6.2, "blockers": 0},
        {"status": "repair", "overall": 6.6, "blockers": 0},
    )
    assert improved
    assert any("audit score improved" in reason for reason in reasons)


def test_new_blocker_is_always_regression():
    improved, reasons = evidence_improved(
        {"status": "repair", "overall": 6.2, "blockers": 0},
        {"status": "advance", "overall": 8.0, "blockers": 1},
    )
    assert not improved
    assert reasons == ["child introduced additional blockers"]


def test_verdict_regression_is_not_improvement():
    improved, reasons = evidence_improved(
        {"status": "repair", "overall": 6.2, "blockers": 1},
        {"status": "reject", "overall": 8.0, "blockers": 0},
    )
    assert not improved
    assert reasons == ["child verdict regressed"]
