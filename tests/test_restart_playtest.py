from game_engine.restart_playtest import assess_restart


def snapshot(**overrides):
    row = {
        "elapsed_ms": 250.0,
        "tick": 0,
        "state": "playing",
        "alive": True,
        "game_over": False,
        "score": 0,
        "progress": 0.0,
        "restart_count": 0,
        "entity_count": 1,
        "action_count": 0,
        "last_action_ms": None,
        "core_mechanic_activations": 0,
        "progression_transitions": 0,
        "state_hash": "fresh",
    }
    row.update(overrides)
    return row


def test_true_fresh_run_restart_passes_cross_checked_evidence():
    baseline = snapshot()
    before = snapshot(
        elapsed_ms=700.0,
        score=10,
        progress=0.5,
        action_count=1,
        last_action_ms=500.0,
        core_mechanic_activations=1,
        state_hash="mutated",
    )
    after = snapshot(elapsed_ms=120.0, restart_count=1)

    result = assess_restart(
        baseline,
        before,
        after,
        restart_events=[{"type": "run_start"}, {"type": "restart"}],
        baseline_visible_hash="fresh-pixels",
        before_visible_hash="mutated-pixels",
        after_visible_hash="fresh-pixels",
    )
    (
        ok,
        pre_restart_mutated,
        independent_visual_mutation,
        restart_visual_response,
        visual_returned_to_baseline,
        restart_event_seen,
        violations,
        warnings,
    ) = result
    assert ok is True
    assert pre_restart_mutated is True
    assert independent_visual_mutation is True
    assert restart_visual_response is True
    assert visual_returned_to_baseline is True
    assert restart_event_seen is True
    assert violations == []
    assert warnings == []


def test_counter_only_restart_cannot_hide_stale_game_state():
    baseline = snapshot()
    before = snapshot(
        elapsed_ms=700.0,
        score=10,
        progress=0.5,
        action_count=1,
        last_action_ms=500.0,
        core_mechanic_activations=1,
        state_hash="mutated",
    )
    after = snapshot(
        elapsed_ms=100.0,
        score=10,
        progress=0.5,
        restart_count=1,
        action_count=1,
        last_action_ms=500.0,
        core_mechanic_activations=1,
        state_hash="mutated",
    )

    result = assess_restart(
        baseline,
        before,
        after,
        restart_events=[{"type": "restart"}],
        baseline_visible_hash="fresh-pixels",
        before_visible_hash="mutated-pixels",
        after_visible_hash="mutated-pixels",
    )
    ok, _, _, restart_visual_response, _, restart_event_seen, violations, _ = result
    assert ok is False
    assert restart_visual_response is False
    assert restart_event_seen is True
    text = "\n".join(violations)
    assert "no independent player-visible response" in text
    assert "restore score" in text
    assert "restore progress" in text
    assert "restore action_count" in text
    assert "stale last_action_ms" in text
    assert "state_hash stayed identical" in text
