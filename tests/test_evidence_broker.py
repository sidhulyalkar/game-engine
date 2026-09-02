from game_engine.evidence_broker import combine_behavioral_evidence


def action(pass_ids=(), fail_ids=()):
    return {
        "action_causality_pass_build_ids": list(pass_ids),
        "action_causality_fail_build_ids": list(fail_ids),
    }


def restart(pass_ids=(), fail_ids=()):
    return {
        "restart_pass_build_ids": list(pass_ids),
        "restart_fail_build_ids": list(fail_ids),
    }


def visual(independent=(), contradictions=(), tested=("a",)):
    return {
        "independently_observable_build_ids": list(independent),
        "telemetry_visual_contradiction_build_ids": list(contradictions),
        "builds": [{"build_id": build_id} for build_id in tested],
    }


def decision(result, build_id="a"):
    return next(row for row in result["decisions"] if row["build_id"] == build_id)


def test_all_independent_behavioral_gates_qualify_for_llm_critics():
    result = combine_behavioral_evidence(
        ["a"],
        action(pass_ids=["a"]),
        restart(pass_ids=["a"]),
        visual(independent=["a"]),
    )
    row = decision(result)
    assert row["status"] == "behaviorally_qualified"
    assert row["eligible_for_llm_critics"] is True
    assert result["llm_critic_eligible_build_ids"] == ["a"]
    assert row["blockers"] == []
    assert row["evidence_gaps"] == []


def test_dead_required_control_is_repair_signal_not_terminal_rejection():
    result = combine_behavioral_evidence(
        ["a"],
        action(fail_ids=["a"]),
        restart(pass_ids=["a"]),
        visual(independent=["a"]),
    )
    row = decision(result)
    assert row["status"] == "behavioral_repair"
    assert row["eligible_for_llm_critics"] is False
    assert any("advertised required controls" in item for item in row["blockers"])


def test_fake_restart_blocks_critic_spend():
    result = combine_behavioral_evidence(
        ["a"],
        action(pass_ids=["a"]),
        restart(fail_ids=["a"]),
        visual(independent=["a"]),
    )
    row = decision(result)
    assert row["status"] == "behavioral_repair"
    assert any("restart" in item for item in row["blockers"])
    assert result["llm_critic_eligible_build_ids"] == []


def test_telemetry_visual_contradiction_cannot_self_certify_mechanic():
    result = combine_behavioral_evidence(
        ["a"],
        action(pass_ids=["a"]),
        restart(pass_ids=["a"]),
        visual(independent=[], contradictions=["a"]),
    )
    row = decision(result)
    assert row["status"] == "behavioral_repair"
    assert row["telemetry_visual_contradiction"] is True
    assert any("independent visual support" in item for item in row["blockers"])


def test_probe_outage_is_insufficient_evidence_not_candidate_failure():
    result = combine_behavioral_evidence(
        ["a"],
        None,
        restart(pass_ids=["a"]),
        visual(independent=["a"]),
    )
    row = decision(result)
    assert row["status"] == "insufficient_evidence"
    assert row["eligible_for_llm_critics"] is False
    assert row["blockers"] == []
    assert "required-control causality evidence missing" in row["evidence_gaps"]


def test_builds_are_classified_independently_without_cross_contamination():
    result = combine_behavioral_evidence(
        ["a", "b"],
        action(pass_ids=["a"], fail_ids=["b"]),
        restart(pass_ids=["a", "b"]),
        visual(independent=["a", "b"], tested=["a", "b"]),
    )
    assert decision(result, "a")["status"] == "behaviorally_qualified"
    assert decision(result, "b")["status"] == "behavioral_repair"
    assert result["llm_critic_eligible_build_ids"] == ["a"]
