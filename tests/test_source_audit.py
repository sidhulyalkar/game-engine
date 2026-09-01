from game_engine.source_audit import AuditFinding, CriticAudit, aggregate_audits


def audit(provider, verdict, score=8.0, findings=None):
    dims = {
        "concept_fidelity": score,
        "logic_correctness": score,
        "first_10s_clarity": score,
        "game_feel": score,
        "mastery_curve": score,
        "pacing_progression": score,
        "visual_identity": score,
        "audio_feedback": score,
        "replayability": score,
        "exploit_resistance": score,
    }
    return CriticAudit(provider=provider, build_id="abc", ok=True, scores=dims, verdict=verdict, findings=findings or [])


def test_two_clean_critics_can_advance():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "advance"), audit("b", "advance", 7.6)],
    )
    assert result.status == "advance"
    assert result.blockers == 0
    assert result.critic_count == 2


def test_blocker_prevents_advance():
    blocker = AuditFinding("blocker", "logic", "cleanup compares object to number", "entities leak", "compare y to height")
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "repair", findings=[blocker]), audit("b", "advance")],
    )
    assert result.status == "repair"
    assert result.blockers == 1


def test_no_successful_critics_rejects():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [CriticAudit(provider="a", build_id="abc", ok=False, error="timeout")],
    )
    assert result.status == "reject"
    assert result.critic_count == 0
