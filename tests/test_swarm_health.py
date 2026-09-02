import json
from dataclasses import asdict

from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm_health import (
    assess_combined_health,
    assess_primary_health,
    build_rescue_config,
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
    assert health["coverage_quorum"] is False
    assert health["heterogeneous_models"] is False
    assert health["evidence_confidence"] == "single-family"
    assert health["successful_models"] == ["nemotron-model"]
    assert health["missing_roles"] == ["gameplay_director", "competition_judge", "desktop_specialist"]


def test_rescue_redundantly_assigns_every_missing_critical_role():
    brief = Brief(theme="x", primary_category="desktop", expansion_categories=["online"])
    primary = {
        "missing_roles": ["gameplay_director", "competition_judge", "desktop_specialist"],
        "successful_models": ["nemotron-model"],
        "successful_assignments": 3,
    }
    rescue_specs = [
        spec("nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("kimi-rescue", "kimi-model", ["gameplay_director", "competition_judge", "online_specialist", "desktop_specialist"]),
    ]
    config = build_rescue_config(rescue_specs, primary, brief)
    by_name = {row["name"]: row for row in config["providers"]}
    expected = ["gameplay_director", "competition_judge", "desktop_specialist"]
    assert by_name["nemotron-rescue"]["roles"] == expected
    assert by_name["kimi-rescue"]["roles"] == expected
    assert "online_specialist" not in by_name["kimi-rescue"]["roles"]
    assert config["rescue_reason"]["need_model_diversity"] is True
    assert config["rescue_reason"]["redundant_critical_roles"] == sorted(expected)
    assert config["rescue_reason"]["uncovered_missing_roles"] == []


def test_single_model_final_coverage_qualifies_with_lower_confidence():
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
    assert health["qualified"] is True
    assert health["coverage_quorum"] is True
    assert health["heterogeneous_models"] is False
    assert health["evidence_confidence"] == "single-family"
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
    assert health["heterogeneous_models"] is True
    assert health["evidence_confidence"] == "heterogeneous"
    assert health["missing_roles"] == []
    assert health["successful_models"] == ["kimi-model", "nemotron-model"]


def _write_specs(path, specs):
    path.write_text(json.dumps({"providers": [asdict(row) for row in specs]}))


def test_exact_live_outage_shape_reaches_final_coverage_with_nemotron_fallback(tmp_path):
    """Replay run 33584569803 without making remote calls.

    Primary returned only three Nemotron roles. DeepSeek and Kimi timed out. Rescue
    then recovered gameplay/judge with Nemotron while Kimi timed out again, leaving
    Desktop uncovered in the old policy. The new roster gives Nemotron Desktop
    fallback too and treats surviving one-family coverage as lower-confidence evidence
    rather than erasing the entire concept stage.
    """
    brief = Brief(theme="Unicorns and Rainbows", primary_category="desktop", expansion_categories=["online", "webxr"])
    primary_specs = [
        spec("nvidia-nemotron-super", "nemotron-model", ["wild_inventor", "byte_architect", "adversarial_designer"]),
        spec("nvidia-deepseek-v4-pro", "deepseek-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("nvidia-kimi-k3", "kimi-model", ["visual_director", "audio_director", "onboarding_critic"]),
    ]
    rescue_specs = [
        spec("nvidia-nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
        spec("nvidia-kimi-rescue", "kimi-model", ["gameplay_director", "competition_judge", "online_specialist", "desktop_specialist"]),
    ]
    primary_contributions = [
        {"provider": "nvidia-nemotron-super", "role": "wild_inventor", "ok": True},
        {"provider": "nvidia-nemotron-super", "role": "byte_architect", "ok": True},
        {"provider": "nvidia-nemotron-super", "role": "adversarial_designer", "ok": True},
        {"provider": "nvidia-deepseek-v4-pro", "role": "gameplay_director", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "competition_judge", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-deepseek-v4-pro", "role": "desktop_specialist", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-kimi-k3", "role": "visual_director", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-kimi-k3", "role": "audio_director", "ok": False, "error": "RuntimeError: TimeoutError"},
        {"provider": "nvidia-kimi-k3", "role": "onboarding_critic", "ok": False, "error": "RuntimeError: TimeoutError"},
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
    assert primary_health["failure_classes"] == {"transport": 6}
    assert primary_health["coverage_repair_required"] is True
    assert primary_health["rescue_plannable"] is True

    generated = json.loads((health_dir / "rescue.generated.json").read_text())
    generated_by_name = {row["name"]: row for row in generated["providers"]}
    expected_roles = ["gameplay_director", "competition_judge", "desktop_specialist"]
    assert generated_by_name["nvidia-nemotron-rescue"]["roles"] == expected_roles
    assert generated_by_name["nvidia-kimi-rescue"]["roles"] == expected_roles

    rescue_contribution_path = tmp_path / "rescue-contributions.json"
    rescue_contribution_path.write_text(json.dumps([
        {"provider": "nvidia-nemotron-rescue", "role": "gameplay_director", "ok": True},
        {"provider": "nvidia-nemotron-rescue", "role": "competition_judge", "ok": True},
        {"provider": "nvidia-nemotron-rescue", "role": "desktop_specialist", "ok": True},
        {"provider": "nvidia-kimi-rescue", "role": "gameplay_director", "ok": False, "error": "RuntimeError: TimeoutError", "failure_class": "transport"},
        {"provider": "nvidia-kimi-rescue", "role": "competition_judge", "ok": False, "error": "RuntimeError: TimeoutError", "failure_class": "transport"},
        {"provider": "nvidia-kimi-rescue", "role": "desktop_specialist", "ok": False, "error": "ProviderCircuitOpen", "failure_class": "circuit_open", "skipped": True},
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
    assert final["coverage_quorum"] is True
    assert final["successful_assignments"] == 6
    assert final["successful_models"] == ["nemotron-model"]
    assert final["missing_roles"] == []
    assert final["heterogeneous_models"] is False
    assert final["evidence_confidence"] == "single-family"
    assert final["skipped_classes"] == {"circuit_open": 1}
    assert final["rescue_used"] is True


def test_complete_single_family_primary_skips_empty_diversity_rescue(tmp_path):
    brief = Brief(theme="x", primary_category="desktop")
    primary_specs = [spec("nemotron", "same-model", ["wild_inventor", "gameplay_director", "competition_judge", "desktop_specialist", "byte_architect"])]
    rescue_specs = [spec("nemotron-rescue", "same-model", ["gameplay_director", "competition_judge", "desktop_specialist"])]
    contributions = [
        {"provider": "nemotron", "role": "wild_inventor", "ok": True},
        {"provider": "nemotron", "role": "gameplay_director", "ok": True},
        {"provider": "nemotron", "role": "competition_judge", "ok": True},
        {"provider": "nemotron", "role": "desktop_specialist", "ok": True},
        {"provider": "nemotron", "role": "byte_architect", "ok": True},
    ]
    manifest = tmp_path / "manifest.json"
    rows = tmp_path / "contributions.json"
    primary_path = tmp_path / "primary.json"
    rescue_path = tmp_path / "rescue.json"
    manifest.write_text(json.dumps({"population_size": 30, "winner_id": "w"}))
    rows.write_text(json.dumps(contributions))
    _write_specs(primary_path, primary_specs)
    _write_specs(rescue_path, rescue_specs)

    health = write_primary_health_plan(
        brief, manifest, rows, primary_path, rescue_path, tmp_path / "health", deterministic_seed_count=24
    )
    assert health["coverage_quorum"] is True
    assert health["heterogeneous_models"] is False
    assert health["rescue_provider_count"] == 0
    assert health["rescue_required"] is False
    assert health["rescue_plannable"] is True
