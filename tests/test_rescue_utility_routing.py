from game_engine.config import ProviderSpec
from game_engine.schema import Brief
from game_engine.swarm_health import build_rescue_config


def spec(name, model, roles):
    return ProviderSpec(
        name=name,
        model=model,
        base_url="https://example.test/v1",
        api_key_env="KEY",
        roles=list(roles),
    )


def utility(models, model_roles=None):
    return {
        "observations": sum(row.get("attempted_assignments", 0) for row in models.values()),
        "models": models,
        "model_roles": model_roles or [],
    }


def test_rescue_utility_prefers_reliable_and_unknown_models_over_known_bad_tie(tmp_path):
    brief = Brief(theme="x", primary_category="desktop")
    primary = {
        "missing_roles": ["gameplay_director"],
        "successful_models": [],
        "successful_assignments": 4,
    }
    specs = [
        spec("good", "good-model", ["gameplay_director"]),
        spec("bad", "bad-model", ["gameplay_director"]),
        spec("unknown", "unknown-model", ["gameplay_director"]),
    ]
    ledger = utility({
        "good-model": {
            "attempted_assignments": 3,
            "smoothed_reliability": 0.8,
            "mean_call_seconds": 10.0,
        },
        "bad-model": {
            "attempted_assignments": 2,
            "smoothed_reliability": 0.25,
            "mean_call_seconds": 90.0,
        },
    })

    config = build_rescue_config(specs, primary, brief, utility_ledger=ledger)
    names = [row["name"] for row in config["providers"]]

    # gameplay_director is critical, so two independent model families are still
    # required. Utility picks the good known model and preserves exploration through
    # the unknown model instead of spending the second slot on a repeatedly bad one.
    assert names == ["good", "unknown"]
    assert config["rescue_reason"]["redundant_critical_roles"] == ["gameplay_director"]
    assert config["rescue_reason"]["assignment_quorum_plannable"] is True
    assert config["rescue_reason"]["utility_policy"] == "tie-break-only"


def test_rescue_utility_never_drops_required_redundancy_when_only_bad_backup_exists():
    brief = Brief(theme="x", primary_category="desktop")
    primary = {
        "missing_roles": ["competition_judge"],
        "successful_models": [],
        "successful_assignments": 4,
    }
    specs = [
        spec("reliable", "reliable-model", ["competition_judge"]),
        spec("unreliable", "unreliable-model", ["competition_judge"]),
    ]
    ledger = utility({
        "reliable-model": {
            "attempted_assignments": 4,
            "smoothed_reliability": 0.833333,
            "mean_call_seconds": 8.0,
        },
        "unreliable-model": {
            "attempted_assignments": 4,
            "smoothed_reliability": 0.166667,
            "mean_call_seconds": 120.0,
        },
    })

    config = build_rescue_config(specs, primary, brief, utility_ledger=ledger)
    names = [row["name"] for row in config["providers"]]
    assert names == ["reliable", "unreliable"]
    assert all(row["roles"] == ["competition_judge"] for row in config["providers"])
    assert config["rescue_reason"]["uncovered_missing_roles"] == []


def test_role_specific_history_takes_priority_over_model_wide_history():
    brief = Brief(theme="x", primary_category="desktop")
    primary = {
        "missing_roles": ["desktop_specialist"],
        "successful_models": [],
        "successful_assignments": 4,
    }
    specs = [
        spec("a", "model-a", ["desktop_specialist"]),
        spec("b", "model-b", ["desktop_specialist"]),
        spec("c", "model-c", ["desktop_specialist"]),
    ]
    ledger = utility(
        {
            "model-a": {
                "attempted_assignments": 8,
                "smoothed_reliability": 0.9,
                "mean_call_seconds": 5.0,
            },
            "model-b": {
                "attempted_assignments": 4,
                "smoothed_reliability": 0.6,
                "mean_call_seconds": 15.0,
            },
        },
        model_roles=[
            {
                "model": "model-a",
                "role": "desktop_specialist",
                "attempted_assignments": 3,
                "smoothed_reliability": 0.2,
                "mean_call_seconds": 80.0,
            },
            {
                "model": "model-b",
                "role": "desktop_specialist",
                "attempted_assignments": 2,
                "smoothed_reliability": 0.75,
                "mean_call_seconds": 12.0,
            },
        ],
    )

    config = build_rescue_config(specs, primary, brief, utility_ledger=ledger)
    names = [row["name"] for row in config["providers"]]
    # Critical redundancy selects two models. Exact-role evidence keeps model-b first,
    # while the unseen model-c remains preferable to model-a's poor Desktop record.
    assert names == ["b", "c"]
