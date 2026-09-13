import json

from game_engine.provider_history import compile_provider_history


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def contribution(provider, role, ok, *, skipped=False, elapsed=None, model="model", failure=None):
    row = {
        "provider": provider,
        "model": model,
        "role": role,
        "ok": ok,
        "concept_ids": ["x"] if ok else [],
        "skipped": skipped,
    }
    if elapsed is not None:
        row["elapsed_seconds"] = elapsed
    if failure is not None:
        row["failure_class"] = failure
    return row


def test_history_keeps_primary_and_rescue_aliases_separate_across_runs(tmp_path):
    r1 = tmp_path / "run1"
    r2 = tmp_path / "run2"
    write_json(r1 / "swarm-primary" / "contributions.json", [
        contribution("kimi-primary", "visual_director", False, elapsed=100, model="kimi", failure="transport"),
        contribution("kimi-primary", "audio_director", True, elapsed=20, model="kimi"),
    ])
    write_json(r1 / "swarm-rescue" / "contributions.json", [
        contribution("kimi-rescue", "gameplay_director", True, elapsed=10, model="kimi"),
        contribution("kimi-rescue", "desktop_specialist", True, elapsed=11, model="kimi"),
    ])
    write_json(r2 / "swarm-primary" / "contributions.json", [
        contribution("kimi-primary", "visual_director", False, elapsed=90, model="kimi", failure="transport"),
        contribution("kimi-primary", "audio_director", False, skipped=True, elapsed=0.001, model="kimi", failure="circuit_open"),
    ])
    write_json(r2 / "swarm-rescue" / "contributions.json", [
        contribution("kimi-rescue", "gameplay_director", True, elapsed=9, model="kimi"),
        contribution("kimi-rescue", "competition_judge", False, elapsed=12, model="kimi", failure="transport"),
    ])

    history = compile_provider_history([r1, r2])
    assert history["routing_authority"] is False
    primary = history["providers"]["kimi-primary"]["ideation"]
    rescue = history["providers"]["kimi-rescue"]["ideation"]

    assert primary["assignments"] == 4
    assert primary["attempts"] == 3
    assert primary["successes"] == 1
    assert primary["skipped"] == 1
    assert primary["latency_observations"] == 3
    assert primary["observed_call_seconds"] == 210.0
    assert primary["models"] == {"kimi": 4}
    assert primary["roles"]["visual_director"]["successes"] == 0
    assert primary["roles"]["visual_director"]["attempts"] == 2

    assert rescue["assignments"] == 4
    assert rescue["attempts"] == 4
    assert rescue["successes"] == 3
    assert rescue["models"] == {"kimi": 4}
    assert rescue["roles"]["gameplay_director"]["successes"] == 2
    assert rescue["roles"]["gameplay_director"]["smoothed_reliability"] == 0.75
    assert primary["smoothed_reliability"] != rescue["smoothed_reliability"]


def test_history_preserves_unknown_latency_as_unobserved(tmp_path):
    run = tmp_path / "legacy"
    write_json(run / "swarm-primary" / "contributions.json", [
        {"provider": "legacy", "role": "judge", "ok": True, "concept_ids": ["x"], "skipped": False}
    ])
    history = compile_provider_history([run])
    idea = history["providers"]["legacy"]["ideation"]
    assert idea["latency_observations"] == 0
    assert idea["observed_call_seconds"] == 0
    assert idea["mean_call_seconds"] is None
    assert idea["smoothed_reliability"] == 0.666667


def test_history_aggregates_builder_and_critic_reliability_without_global_score(tmp_path):
    r1 = tmp_path / "run1"
    r2 = tmp_path / "run2"
    for root, builder_ok, critic_ok in ((r1, True, False), (r2, True, True)):
        write_json(root / "builds-a" / "builds.json", [
            {"provider": "builder", "build_id": root.name, "ok": builder_ok, "compressed_bytes": 3000}
        ])
        write_json(root / "audit-a" / "audits.json", [
            {"provider": "critic", "build_id": root.name, "ok": critic_ok, "recovery_attempted": False}
        ])

    history = compile_provider_history([r1, r2])
    assert history["providers"]["builder"]["builder"]["successes"] == 2
    assert history["providers"]["builder"]["builder"]["smoothed_reliability"] == 0.75
    assert history["providers"]["critic"]["critics"]["successes"] == 1
    assert history["providers"]["critic"]["critics"]["smoothed_reliability"] == 0.5
    assert "score" not in history["providers"]["builder"]
    assert "rank" not in history["providers"]["builder"]
