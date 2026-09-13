import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())["providers"]


def test_deepseek_primary_is_bounded_canary_not_critical_role_keyholder():
    providers = {row["name"]: row for row in load("studio.nvidia.json")}
    deepseek = providers["nvidia-deepseek-v4-pro"]
    assert deepseek["enabled"] is True
    assert deepseek["roles"] == ["competition_judge"]
    assert deepseek["max_concurrency"] == 1
    assert deepseek["retries"] == 0


def test_rescue_keeps_two_independent_families_for_all_desktop_critical_roles():
    providers = load("studio.nvidia.rescue.json")
    critical = {"gameplay_director", "competition_judge", "desktop_specialist"}
    models_by_role = {role: set() for role in critical}
    for row in providers:
        for role in critical & set(row["roles"]):
            models_by_role[role].add(row["model"])

    assert all(len(models) >= 2 for models in models_by_role.values())


def test_deepseek_canary_failure_cannot_make_rescue_mathematically_impossible():
    rescue = load("studio.nvidia.rescue.json")
    total_desktop_critical_assignments = sum(
        len({"gameplay_director", "competition_judge", "desktop_specialist"} & set(row["roles"]))
        for row in rescue
    )
    # A complete primary critical-role miss can still schedule the five-assignment
    # final quorum with redundant critical coverage.
    assert total_desktop_critical_assignments >= 5
