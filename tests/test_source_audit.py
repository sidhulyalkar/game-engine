import json

from game_engine.source_audit import AuditFinding, CriticAudit, _filter_browser_qualified, aggregate_audits


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
    assert result.failed_critic_count == 0


def test_blocker_prevents_advance():
    blocker = AuditFinding("blocker", "logic", "cleanup compares object to number", "entities leak", "compare y to height")
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "repair", findings=[blocker]), audit("b", "advance")],
    )
    assert result.status == "repair"
    assert result.blockers == 1


def test_no_successful_critics_is_insufficient_evidence_not_rejection():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [CriticAudit(provider="a", build_id="abc", ok=False, error="timeout")],
    )
    assert result.status == "insufficient_evidence"
    assert result.critic_count == 0
    assert result.failed_critic_count == 1


def test_one_successful_critic_is_still_insufficient_for_independent_quorum():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "reject", 2.0), CriticAudit(provider="b", build_id="abc", ok=False, error="schema")],
    )
    assert result.status == "insufficient_evidence"
    assert result.critic_count == 1
    assert result.failed_critic_count == 1
    assert result.verdict_votes["reject"] == 1


def test_two_independent_rejects_are_candidate_evidence():
    result = aggregate_audits(
        {"build_id": "abc", "provider": "builder"},
        [audit("a", "reject", 2.0), audit("b", "reject", 3.0)],
    )
    assert result.status == "reject"
    assert result.critic_count == 2


def test_browser_qualification_filters_expensive_critic_field(tmp_path):
    reality = tmp_path / "reality"
    reality.mkdir()
    (reality / "qualification.json").write_text(json.dumps({"full_pass_build_ids": ["keep"]}))
    builds = [
        {"build_id": "keep", "provider": "a"},
        {"build_id": "drop", "provider": "b"},
    ]
    assert _filter_browser_qualified(builds, reality) == [{"build_id": "keep", "provider": "a"}]
