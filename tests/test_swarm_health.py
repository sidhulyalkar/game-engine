import json
from dataclasses import asdict

from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm_health import (
    assess_combined_health,
    assess_primary_health,
    build_rescue_config,
    contribution_summary,
    write_combined_health,
    write_primary_health_plan,
)


def spec(name, model, roles):
    return ProviderSpec(
        name=name,
        model=model,
        base_url="https://example.test/v1",
        api_key_env="KEY",
        roles=list(roles),
    )


def test_one_model_with_real_population_is_degraded_not_failed():
    brief = Brief(theme="x", primary_category="desktop")
    specs = [
        spec("nemotron", "nemotron-model", ["wild_inventor", "byte_architect", "adversarial_designer"]),
        spec("deepseek", "deepseek-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("kimi", "kimi-model", ["visual_director", "audio_director", "onboarding_critic"]),
    ]
    contributions = [
        {"provider": "nemotron", "role": "wild_inventor", "ok": True},
        {"provider": "nemotron", "role": "byte_architect", "ok": True},
        {"provider": "nemotron", "role": "adversarial_designer", "ok": True},
        {"provider": "deepseek", "role": "gameplay_director", "ok": False, "error": "TimeoutError"},
        {"provider": "deepseek", "role": "competition_judge", "ok": False, "error": "TimeoutError"},
        {"provider": "deepseek", "role": "desktop_specialist", "ok": False, "error": "TimeoutError"},
    ]
    health = assess_primary_health(
        {"population_size": 32, "winner_id": "winner"},
        contributions,
        specs,
        brief,
        deterministic_seed_count=24,
    )
    assert health["status"] == "degraded"
    assert health["rescue_required"] is True
    assert health["successful_models"] == ["nemotron-model"]
    assert health["missing_roles"] == ["gameplay_director", "competition_judge", "desktop_specialist"]


def test_rescue_targets_missing_roles_and_requires_novel_model_family():
    brief = Brief(theme="x", primary_category="desktop", expansion_categories=["online"])
    primary = {
        "missing_roles": ["gameplay_director", "competition_judge", "desktop_specialist"],
        "successful_models": ["nemotron-model"],
    }
    rescue_specs = [
        spec("nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge"]),
        spec("kimi-rescue", "kimi-model", ["online_specialist", "desktop_specialist"]),
    ]
    config = build_rescue_config(rescue_specs, primary, brief)
    by_name = {row["name"]: row for row in config["providers"]}
    assert by_name["nemotron-rescue"]["roles"] == ["gameplay_director", "competition_judge"]
    assert by_name["kimi-rescue"]["roles"] == ["desktop_specialist"]
    assert "online_specialist" not in by_name["kimi-rescue"]["roles"]
    assert config["rescue_reason"]["need_model_diversity"] is True


def test_provider_aliases_of_same_model_do_not_satisfy_combined_diversity():
    brief = Brief(theme="x", primary_category="desktop")
    primary_specs = [spec("nemotron", "same-model", ["wild_inventor"])]
    rescue_specs = [spec("nemotron-rescue", "same-model", ["gameplay_director", "competition_judge", "desktop_specialist"])]
    health = assess_combined_health(
        [
            [{"provider": "nemotron", "role": "wild_inventor", "ok": True}],
            [
                {"provider": "nemotron-rescue", "role": "gameplay_director", "ok": True},
                {"provider": "nemotron-rescue", "role": "competition_judge", "ok": True},
                {"provider": "nemotron-rescue", "role": "desktop_specialist", "ok": True},
                {"provider": "nemotron-rescue", "role": "gameplay_director", "ok": True},
            ],
        ],
        [primary_specs, rescue_specs],
        brief,
    )
    assert health["qualified"] is False
    assert health["successful_models"] == ["same-model"]


def test_two_models_and_critical_coverage_qualify_combined_swarm():
    brief = Brief(theme="x", primary_category="desktop")
    primary_specs = [spec("nemotron", "nemotron-model", ["wild_inventor", "byte_architect"])]
    rescue_specs = [spec("kimi", "kimi-model", ["gameplay_director", "competition_judge", "desktop_specialist"])]
    health = assess_combined_health(
        [
            [
                {"provider": "nemotron", "role": "wild_inventor", "ok": True},
                {"provider": "nemotron", "role": "byte_architect", "ok": True},
            ],
            [
                {"provider": "kimi", "role": "gameplay_director", "ok": True},
                {"provider": "kimi", "role": "competition_judge", "ok": True},
                {"provider": "kimi", "role": "desktop_specialist", "ok": True},
            ],
        ],
        [primary_specs, rescue_specs],
        brief,
    )
    assert health["qualified"] is True
    assert health["missing_roles"] == []
    assert health["successful_models"] == ["kimi-model", "nemotron-model"]


def test_circuit_open_skips_are_not_counted_as_real_failures():
    summary = contribution_summary(
        [
            {"provider": "p", "role": "a", "ok": False, "failure_class": "transport", "skipped": False},
            {"provider": "p", "role": "b", "ok": False, "failure_class": "transport", "skipped": False},
            {"provider": "p", "role": "c", "ok": False, "failure_class": "circuit_open", "skipped": True},
        ],
        {"p": "model"},
    )
    assert summary["failure_classes"] == {"transport": 2}
    assert summary["skipped_classes"] == {"circuit_open": 1}
    assert summary["skipped_assignments"] == 1


def _write_specs(path, specs):
    path.write_text(json.dumps({"providers": [asdict(row) for row in specs]}))


def test_live_failure_shape_writes_targeted_rescue_and_can_finalize(tmp_path):
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop", expansion_categories=["online", "webxr"])
    primary_specs = [
        spec("nvidia-nemotron-super", "nemotron-model", ["wild_inventor", "byte_architect", "adversarial_designer"]),
        spec("nvidia-deepseek-v4-pro", "deepseek-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("nvidia-kimi-k3", "kimi-model", ["visual_director", "audio_director", "onboarding_critic"]),
    ]
    rescue_specs = [
        spec("nvidia-nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge"]),
        spec("nvidia-kimi-rescue", "kimi-model", ["online_specialist", "desktop_specialist"]),
    ]
    primary_contributions = [
        {"provider": "nvidia-nemotron-super", "role": "wild_inventor", "ok": True},
        {"provider": "nvidia-nemotron-super", "role": "byte_architect", "ok": True},
        {"provider": "nvidia-nemotron-super", "role": "adversarial_designer", "ok": True},
        {"provider": "nvidia-deepseek-v4-pro", "role": "gameplay_director", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "competition_judge", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "desktop_specialist", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-kimi-k3", "role": "visual_director", "ok": False, "error": "ValueError: core_mechanic exceeds 90 words"},
        {"provider": "nvidia-kimi-k3", "role": "audio_director", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-kimi-k3", "role": "onboarding_critic", "ok": False, "error": "ValueError: core_mechanic exceeds 90 words"},
    ]

    manifest_path = tmp_path / "manifest.json"
    contribution_path = tmp_path / "contributions.json"
    primary_config_path = tmp_path / "primary.json"
    rescue_config_path = tmp_path / "rescue.json"
    health_dir = tmp_path / "health"
    manifest_path.write_text(json.dumps({"population_size": 32, "winner_id": "a441a247"}))
    contribution_path.write_text(json.dumps(primary_contributions))
    _write_specs(primary_config_path, primary_specs)
    _write_specs(rescue_config_path, rescue_specs)

    primary_health = write_primary_health_plan(
        brief,
        manifest_path,
        contribution_path,
        primary_config_path,
        rescue_config_path,
        health_dir,
        deterministic_seed_count=24,
    )
    assert primary_health["status"] == "degraded"
    assert primary_health["failure_classes"] == {"content_or_schema": 2, "transport": 4}
    assert primary_health["skipped_assignments"] == 0
    generated = json.loads((health_dir / "rescue.generated.json").read_text())
    generated_by_name = {row["name"]: row for row in generated["providers"]}
    assert generated_by_name["nvidia-nemotron-rescue"]["roles"] == ["gameplay_director", "competition_judge"]
    assert generated_by_name["nvidia-kimi-rescue"]["roles"] == ["desktop_specialist"]

    rescue_contribution_path = tmp_path / "rescue-contributions.json"
    rescue_contribution_path.write_text(json.dumps([
        {"provider": "nvidia-nemotron-rescue", "role": "gameplay_director", "ok": True},
        {"provider": "nvidia-nemotron-rescue", "role": "competition_judge", "ok": True},
        {"provider": "nvidia-kimi-rescue", "role": "desktop_specialist", "ok": True},
    ]))
    final = write_combined_health(
        brief,
        contribution_path,
        primary_config_path,
        health_dir,
        rescue_contributions_path=rescue_contribution_path,
        rescue_specs_path=health_dir / "rescue.generated.json",
    )
    assert final["qualified"] is True
    assert final["successful_models"] == ["kimi-model", "nemotron-model"]
    assert final["missing_roles"] == []
    assert final["rescue_used"] is True
