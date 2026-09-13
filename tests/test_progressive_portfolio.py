import pytest

from game_engine.progressive_portfolio import plan_progressive_prototypes


def portfolio():
    return {
        "members": [
            {"slot": 1, "concept_id": "inc", "title": "Tension Trail", "is_incumbent": True, "joint_score": 7.775, "nearest_prior_distance": None},
            {"slot": 2, "concept_id": "herd", "title": "Rainbow Stampede", "is_incumbent": False, "joint_score": 7.605, "nearest_prior_distance": 0.96},
            {"slot": 3, "concept_id": "prism", "title": "Prism Fold", "is_incumbent": False, "joint_score": 7.564, "nearest_prior_distance": 0.86},
            {"slot": 4, "concept_id": "horn", "title": "Horn Stampede", "is_incumbent": False, "joint_score": 7.598, "nearest_prior_distance": 0.60},
        ]
    }


def test_two_hypotheses_fit_same_four_call_ceiling_with_two_confirmation_slots():
    plan = plan_progressive_prototypes(
        portfolio(),
        initial_concepts=2,
        max_total_builder_calls=4,
        confirmation_builds_per_survivor=1,
    )
    assert plan["initial_concepts"] == 2
    assert plan["initial_builder_calls"] == 2
    assert plan["remaining_confirmation_calls"] == 2
    assert plan["max_confirmed_survivors"] == 2
    assert [row["concept_id"] for row in plan["slots"]] == ["inc", "herd"]
    assert plan["incumbent_present"] is True
    assert plan["build_authority"] is False
    assert plan["routing_authority"] is False
    assert "source_semantics" in plan["slots"][0]["confirmation_eligible_after"]
    assert "causal_controls" in plan["slots"][0]["confirmation_eligible_after"]


def test_builder_ceiling_truncates_initial_breadth_instead_of_overcommitting():
    plan = plan_progressive_prototypes(
        portfolio(),
        initial_concepts=4,
        max_total_builder_calls=2,
    )
    assert plan["initial_concepts"] == 2
    assert plan["initial_builder_calls"] == 2
    assert plan["remaining_confirmation_calls"] == 0
    assert plan["max_confirmed_survivors"] == 0


def test_zero_confirmation_policy_is_explicit_and_does_not_divide_by_zero():
    plan = plan_progressive_prototypes(
        portfolio(),
        initial_concepts=3,
        max_total_builder_calls=4,
        confirmation_builds_per_survivor=0,
    )
    assert plan["initial_builder_calls"] == 3
    assert plan["remaining_confirmation_calls"] == 1
    assert plan["max_confirmed_survivors"] == 0


def test_progressive_plan_rejects_empty_or_invalid_budgets():
    with pytest.raises(ValueError, match="non-empty portfolio"):
        plan_progressive_prototypes({"members": []})
    with pytest.raises(ValueError, match="initial_concepts"):
        plan_progressive_prototypes(portfolio(), initial_concepts=0)
    with pytest.raises(ValueError, match="max_total_builder_calls"):
        plan_progressive_prototypes(portfolio(), max_total_builder_calls=0)
    with pytest.raises(ValueError, match="confirmation_builds_per_survivor"):
        plan_progressive_prototypes(portfolio(), confirmation_builds_per_survivor=-1)
