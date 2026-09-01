from game_engine.playtest import (
    PolicyTrace,
    TelemetrySample,
    _summarize_trace,
    summarize_playtests,
    validate_snapshot,
)


def snapshot(**updates):
    value = {
        "elapsed_ms": 0,
        "tick": 0,
        "state": "playing",
        "alive": True,
        "game_over": False,
        "score": 0,
        "progress": 0.0,
        "restart_count": 0,
        "entity_count": 4,
        "action_count": 0,
        "last_action_ms": None,
        "core_mechanic_activations": 0,
        "progression_transitions": 0,
        "state_hash": "start",
    }
    value.update(updates)
    return value


def sample(at_ms, visible_hash, **updates):
    snap, errors = validate_snapshot(snapshot(**updates))
    assert not errors
    return TelemetrySample(at_ms=at_ms, snapshot=snap, events=[], visible_hash=visible_hash)


def trace(browser, policy, rows, provider="builder"):
    result = PolicyTrace(
        build_id="abc",
        provider=provider,
        browser=browser,
        policy=policy,
        ok=True,
        telemetry_present=True,
        schema_version="0.1",
        schema_valid=True,
        duration_ms=rows[-1].at_ms,
        samples=rows,
    )
    return _summarize_trace(result)


def test_validate_snapshot_accepts_contract_and_rejects_bad_progress():
    normalized, errors = validate_snapshot(snapshot())
    assert normalized is not None
    assert errors == []

    _, errors = validate_snapshot(snapshot(progress=1.5))
    assert "progress should be normalized to 0..1" in errors


def test_validate_snapshot_requires_portable_evidence_fields():
    value = snapshot()
    value.pop("core_mechanic_activations")
    _, errors = validate_snapshot(value)
    assert any("core_mechanic_activations" in error for error in errors)


def test_summary_distinguishes_null_baseline_from_active_response():
    traces = []
    for browser in ("chromium", "firefox"):
        traces.append(trace(browser, "null", [
            sample(0, "still", elapsed_ms=0),
            sample(500, "still", elapsed_ms=500, tick=30),
        ]))
        traces.append(trace(browser, "sweep", [
            sample(0, "before", elapsed_ms=0),
            sample(
                500,
                "after",
                elapsed_ms=500,
                tick=30,
                score=10,
                progress=0.2,
                action_count=1,
                last_action_ms=120,
                core_mechanic_activations=1,
                state_hash="hit-1",
            ),
        ]))

    summary = summarize_playtests(
        traces,
        ["chromium", "firefox"],
        {"state_bounds": {"hazards_or_enemies": 32, "particles_or_trail_points": 256, "timers_or_scheduled_events": 32}},
    )
    assert summary["instrumented_build_ids"] == ["abc"]
    assert summary["mechanically_observable_build_ids"] == ["abc"]
    assert summary["cross_browser_divergence_build_ids"] == []


def test_cross_browser_behavior_difference_is_preserved_as_evidence():
    traces = [
        trace("chromium", "null", [sample(0, "same")]),
        trace("chromium", "sweep", [sample(0, "a"), sample(500, "b", score=5, progress=0.1)]),
        trace("firefox", "null", [sample(0, "same")]),
        trace("firefox", "sweep", [sample(0, "a"), sample(500, "c", score=20, progress=0.5)]),
    ]
    summary = summarize_playtests(traces, ["chromium", "firefox"], {})
    assert summary["cross_browser_divergence_build_ids"] == ["abc"]
    assert summary["instrumented_build_ids"] == ["abc"]


def test_entity_bound_violation_blocks_mechanical_observability_not_instrumentation():
    traces = [
        trace("chromium", "null", [sample(0, "same")]),
        trace("chromium", "sweep", [
            sample(0, "a"),
            sample(500, "b", action_count=1, core_mechanic_activations=1, entity_count=1000),
        ]),
    ]
    summary = summarize_playtests(
        traces,
        ["chromium"],
        {"state_bounds": {"hazards_or_enemies": 10, "particles_or_trail_points": 20, "timers_or_scheduled_events": 5}},
    )
    assert summary["instrumented_build_ids"] == ["abc"]
    assert summary["mechanically_observable_build_ids"] == []
    assert any("entity_count" in violation for violation in summary["builds"][0]["violations"])
