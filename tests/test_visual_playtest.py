from game_engine.playtest import PolicyTrace, TelemetrySample
from game_engine.visual_playtest import augment_visual_evidence


def trace(policy, hashes):
    return PolicyTrace(
        build_id="build",
        provider="fixture",
        browser="chromium",
        policy=policy,
        ok=True,
        telemetry_present=True,
        schema_version="0.1",
        schema_valid=True,
        duration_ms=1000,
        samples=[TelemetrySample(at_ms=i * 100, snapshot=None, events=[], visible_hash=value) for i, value in enumerate(hashes)],
    )


def summary():
    return {
        "builds": [{
            "build_id": "build",
            "provider": "fixture",
            "browsers": ["chromium"],
            "instrumented": True,
            "mechanically_observable": True,
            "cross_browser_divergence": False,
            "violations": [],
            "warnings": [],
            "policies": {"chromium": {"null": {}, "sweep": {}}},
        }]
    }


def test_static_null_and_changing_active_trace_is_independent_response():
    result = augment_visual_evidence(
        summary(),
        [trace("null", ["a", "a", "a", "a"]), trace("sweep", ["a", "b", "c", "d"])],
        ["chromium"],
    )
    build = result["builds"][0]
    assert build["independent_visual_response"] is True
    assert build["policies"]["chromium"]["null"]["visible_change_fraction"] == 0.0
    assert build["policies"]["chromium"]["sweep"]["visible_change_fraction"] == 1.0
    assert result["independent_visual_response_build_ids"] == ["build"]


def test_equal_idle_and_active_animation_is_not_causal_evidence():
    result = augment_visual_evidence(
        summary(),
        [trace("null", ["a", "b", "c", "d"]), trace("sweep", ["q", "r", "s", "t"])],
        ["chromium"],
    )
    build = result["builds"][0]
    assert build["independent_visual_response"] is False
    assert result["independent_visual_response_build_ids"] == []
    assert any("not more responsive than the null baseline" in warning for warning in build["warnings"])
