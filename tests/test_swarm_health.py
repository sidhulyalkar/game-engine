from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm_health import assess_combined_health, assess_primary_health, build_rescue_config


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
