import json
from dataclasses import asdict

from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm_health import write_combined_health, write_primary_health_plan


def spec(name, model, roles):
    return ProviderSpec(
        name=name,
        model=model,
        base_url="https://example.test/v1",
        api_key_env="KEY",
        roles=list(roles),
    )


def write_specs(path, specs):
    path.write_text(json.dumps({"providers": [asdict(row) for row in specs]}))


def test_run_63_zero_success_primary_is_recoverable_when_rescue_can_establish_quorum(tmp_path):
    """Replay autonomous run 33666765803 without remote calls.

    The primary providers produced zero valid LLM assignments, but deterministic
    exploration still produced its full seed population and winner. Both configured
    rescue model families can cover gameplay, judge, and Desktop roles, yielding six
    bounded assignments. The primary stage should therefore proceed to rescue, while
    final qualification still requires real successful LLM contributions.
    """
    brief = Brief(
        theme="Unicorns and Rainbows",
        primary_category="desktop",
        expansion_categories=["mobile", "online", "webxr"],
    )
    primary_specs = [
        spec("nvidia-nemotron-super", "nemotron-model", ["wild_inventor", "byte_architect", "adversarial_designer"]),
        spec("nvidia-deepseek-v4-pro", "deepseek-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("nvidia-kimi-k3", "kimi-model", ["visual_director", "audio_director", "onboarding_critic"]),
    ]
    rescue_specs = [
        spec("nvidia-nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("nvidia-kimi-rescue", "kimi-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
    ]
    primary_contributions = [
        {"provider": "nvidia-nemotron-super", "role": "wild_inventor", "ok": False, "failure_class": "content_or_schema"},
        {"provider": "nvidia-nemotron-super", "role": "byte_architect", "ok": False, "failure_class": "content_or_schema"},
        {"provider": "nvidia-nemotron-super", "role": "adversarial_designer", "ok": False, "failure_class": "content_or_schema"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "gameplay_director", "ok": False, "failure_class": "transport"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "competition_judge", "ok": False, "failure_class": "transport"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "desktop_specialist", "ok": False, "failure_class": "transport"},
        {"provider": "nvidia-kimi-k3", "role": "visual_director", "ok": False, "failure_class": "transport"},
        {"provider": "nvidia-kimi-k3", "role": "audio_director", "ok": False, "failure_class": "transport"},
        {"provider": "nvidia-kimi-k3", "role": "onboarding_critic", "ok": False, "failure_class": "circuit_open", "skipped": True},
    ]

    manifest = tmp_path / "manifest.json"
    contributions = tmp_path / "contributions.json"
    primary_config = tmp_path / "primary.json"
    rescue_config = tmp_path / "rescue.json"
    health_dir = tmp_path / "health"
    manifest.write_text(json.dumps({"population_size": 24, "winner_id": "deterministic-winner"}))
    contributions.write_text(json.dumps(primary_contributions))
    write_specs(primary_config, primary_specs)
    write_specs(rescue_config, rescue_specs)

    health = write_primary_health_plan(
        brief,
        manifest,
        contributions,
        primary_config,
        rescue_config,
        health_dir,
        deterministic_seed_count=24,
    )

    assert health["status"] == "recoverable"
    assert health["usable"] is True
    assert health["primary_llm_usable"] is False
    assert health["deterministic_substrate_usable"] is True
    assert health["successful_assignments"] == 0
    assert health["successful_models"] == []
    assert health["llm_expanded_population"] is False
    assert health["coverage_quorum"] is False
    assert health["rescue_required"] is True
    assert health["rescue_plannable"] is True
    assert health["missing_roles"] == ["gameplay_director", "competition_judge", "desktop_specialist"]
    assert health["failure_classes"] == {"content_or_schema": 3, "transport": 5}
    assert health["skipped_classes"] == {"circuit_open": 1}

    generated = json.loads((health_dir / "rescue.generated.json").read_text())
    reason = generated["rescue_reason"]
    assert reason["uncovered_missing_roles"] == []
    assert reason["planned_assignments"] == 6
    assert reason["planned_total_assignments"] == 6
    assert reason["assignment_quorum_plannable"] is True

    # Deterministic exploration still cannot qualify the concept stage by itself.
    final_without_rescue = write_combined_health(
        brief,
        contributions,
        primary_config,
        health_dir,
    )
    assert final_without_rescue["qualified"] is False
    assert final_without_rescue["successful_assignments"] == 0


def test_zero_success_primary_fails_when_rescue_cannot_reach_assignment_quorum(tmp_path):
    brief = Brief(theme="x", primary_category="desktop")
    primary_specs = [spec("primary", "primary-model", ["wild_inventor"])]
    # This single rescue provider covers the three critical roles but can produce at
    # most three assignments, below the final five-assignment quorum.
    rescue_specs = [
        spec("rescue", "rescue-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
    ]

    manifest = tmp_path / "manifest.json"
    contributions = tmp_path / "contributions.json"
    primary_config = tmp_path / "primary.json"
    rescue_config = tmp_path / "rescue.json"
    manifest.write_text(json.dumps({"population_size": 24, "winner_id": "deterministic-winner"}))
    contributions.write_text(json.dumps([
        {"provider": "primary", "role": "wild_inventor", "ok": False, "failure_class": "transport"},
    ]))
    write_specs(primary_config, primary_specs)
    write_specs(rescue_config, rescue_specs)

    health = write_primary_health_plan(
        brief,
        manifest,
        contributions,
        primary_config,
        rescue_config,
        tmp_path / "health",
        deterministic_seed_count=24,
    )

    assert health["status"] == "failed"
    assert health["usable"] is False
    assert health["primary_llm_usable"] is False
    assert health["deterministic_substrate_usable"] is True
    assert health["rescue_required"] is True
    assert health["rescue_plannable"] is False
    generated = json.loads((tmp_path / "health" / "rescue.generated.json").read_text())
    assert generated["rescue_reason"]["uncovered_missing_roles"] == []
    assert generated["rescue_reason"]["planned_assignments"] == 3
    assert generated["rescue_reason"]["assignment_quorum_plannable"] is False
