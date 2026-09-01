from game_engine.evaluators import deduplicate, judge
from game_engine.idea_space import procedural_concepts
from game_engine.schema import Brief


def test_population_scores_and_deduplicates():
    brief = Brief(theme="Unicorns and Rainbows")
    population = deduplicate(procedural_concepts(brief, count=12, seed=13))
    assert len(population) >= 6
    score = judge(population[0], brief, population)
    assert 0 <= score.total <= 10
    assert set(score.scores) >= {"innovation", "gameplay", "byte_fit", "controls"}
