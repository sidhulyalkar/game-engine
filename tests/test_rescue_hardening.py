import json
from dataclasses import dataclass
from pathlib import Path

from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm import SwarmStudio
from game_engine.swarm_health import assess_combined_health, build_rescue_config


def _spec(name, model, roles):
    return ProviderSpec(
        name=name,
        model=model,
        base_url="https://example.test/v1",
        api_key_env="KEY",
        roles=list(roles),
    )


def test_missing_universal_roles_get_two_family_rescue_redundancy():
    brief = Brief(
        theme="Unicorns and Rainbows",
        primary_category="desktop",
        expansion_categories=["online", "webxr"],
    )
    health = {
        "missing_roles": ["gameplay_director", "competition_judge", "desktop_specialist"],
        "successful_models": ["nemotron-model", "kimi-model"],
        "successful_assignments": 4,
    }
    rescue_specs = [
        _spec("nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge"]),
        _spec(
            "kimi-rescue",
            "kimi-model",
            ["gameplay_director", "competition_judge", "online_specialist", "desktop_specialist"],
        ),
    ]

    config = build_rescue_config(rescue_specs, health, brief)
    by_name = {row["name"]: row["roles"] for row in config["providers"]}

    assert by_name["nemotron-rescue"] == ["gameplay_director", "competition_judge"]
    assert by_name["kimi-rescue"] == ["gameplay_director", "competition_judge", "desktop_specialist"]
    assert "online_specialist" not in by_name["kimi-rescue"]
    reason = config["rescue_reason"]
    assert reason["redundant_critical_roles"] == ["competition_judge", "gameplay_director"]
    assert reason["uncovered_missing_roles"] == []
    assert reason["planned_assignments"] == 5


def test_second_rescue_family_can_recover_both_universal_role_failures():
    brief = Brief(theme="x", primary_category="desktop")
    primary_specs = [
        _spec("nemotron", "nemotron-model", ["adversarial_designer"]),
        _spec("kimi", "kimi-model", ["visual_director", "audio_director", "onboarding_critic"]),
    ]
    rescue_specs = [
        _spec("nemotron-rescue", "nemotron-model", ["gameplay_director", "competition_judge"]),
        _spec("kimi-rescue", "kimi-model", ["gameplay_director", "competition_judge", "desktop_specialist"]),
    ]
    primary = [
        {"provider": "nemotron", "role": "adversarial_designer", "ok": True},
        {"provider": "kimi", "role": "visual_director", "ok": True},
        {"provider": "kimi", "role": "audio_director", "ok": True},
        {"provider": "kimi", "role": "onboarding_critic", "ok": True},
    ]
    rescue = [
        {
            "provider": "nemotron-rescue",
            "role": "gameplay_director",
            "ok": False,
            "error": "JSONDecodeError: empty response",
        },
        {
            "provider": "nemotron-rescue",
            "role": "competition_judge",
            "ok": False,
            "error": "JSONDecodeError: empty response",
        },
        {"provider": "kimi-rescue", "role": "gameplay_director", "ok": True},
        {"provider": "kimi-rescue", "role": "competition_judge", "ok": True},
        {"provider": "kimi-rescue", "role": "desktop_specialist", "ok": True},
    ]

    final = assess_combined_health([primary, rescue], [primary_specs, rescue_specs], brief)
    assert final["qualified"] is True
    assert final["missing_roles"] == []
    assert final["successful_assignments"] == 7
    assert final["successful_models"] == ["kimi-model", "nemotron-model"]


@dataclass
class _MalformedSpec:
    name: str = "malformed-provider"
    roles: tuple[str, ...] = ("wild_inventor",)
    max_concurrency: int = 1


class _MalformedClient:
    name = "malformed-provider"

    def complete(self, system: str, prompt: str) -> str:
        return "THIS IS A RETURNED RESPONSE BUT IT IS NOT JSON"


def test_swarm_preserves_returned_text_before_parse_failure(tmp_path):
    out = tmp_path / "swarm"
    manifest = SwarmStudio([(_MalformedSpec(), _MalformedClient())], max_workers=1).run(
        Brief(theme="Unicorns and Rainbows"),
        out,
        deterministic_seeds=4,
        concepts_per_call=1,
    )

    assert manifest["failed_assignments"] == 1
    rows = json.loads((out / "contributions.json").read_text())
    row = rows[0]
    assert row["ok"] is False
    assert "JSONDecodeError" in row["error"]
    assert row["response_sha256"] and len(row["response_sha256"]) == 64
    raw_path = Path(row["raw_response_path"])
    assert raw_path.exists()
    assert raw_path.read_text() == "THIS IS A RETURNED RESPONSE BUT IT IS NOT JSON"
    assert raw_path.parent == out / "raw"
