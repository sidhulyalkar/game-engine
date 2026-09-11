import json

from game_engine.experiment_identity import build_experiment_identity, write_experiment_identity


def test_experiment_fingerprint_is_stable_for_same_inputs(tmp_path):
    brief = tmp_path / "brief.json"
    primary = tmp_path / "primary.json"
    brief.write_text('{"theme":"Unicorns and Rainbows"}\n')
    primary.write_text('[{"model":"x"}]\n')

    kwargs = dict(
        brief_path=brief,
        provider_configs={"primary": primary},
        seed=13,
        browsers=("chromium", "firefox", "webkit"),
        git_sha="abc123",
    )
    a = build_experiment_identity(**kwargs)
    b = build_experiment_identity(**kwargs)
    assert a == b
    assert len(a["experiment_fingerprint"]) == 64
    assert a["git_sha"] == "abc123"


def test_config_change_changes_experiment_fingerprint(tmp_path):
    brief = tmp_path / "brief.json"
    config = tmp_path / "providers.json"
    brief.write_text('{"theme":"Unicorns and Rainbows"}\n')
    config.write_text('[{"model":"old"}]\n')
    old = build_experiment_identity(
        brief_path=brief,
        provider_configs={"audit": config},
        seed=1,
        browsers=("chromium",),
        git_sha="same-code",
    )
    config.write_text('[{"model":"new","top_p":null}]\n')
    new = build_experiment_identity(
        brief_path=brief,
        provider_configs={"audit": config},
        seed=1,
        browsers=("chromium",),
        git_sha="same-code",
    )
    assert old["provider_configs"]["audit"]["sha256"] != new["provider_configs"]["audit"]["sha256"]
    assert old["experiment_fingerprint"] != new["experiment_fingerprint"]


def test_brief_seed_browser_or_git_change_keeps_runs_distinguishable(tmp_path):
    brief = tmp_path / "brief.json"
    config = tmp_path / "providers.json"
    brief.write_text('{"theme":"Unicorns and Rainbows"}\n')
    config.write_text('[]\n')
    base = build_experiment_identity(
        brief_path=brief,
        provider_configs={"primary": config},
        seed=13,
        browsers=("chromium",),
        git_sha="a",
    )["experiment_fingerprint"]
    variants = [
        build_experiment_identity(brief_path=brief, provider_configs={"primary": config}, seed=14, browsers=("chromium",), git_sha="a"),
        build_experiment_identity(brief_path=brief, provider_configs={"primary": config}, seed=13, browsers=("chromium", "firefox"), git_sha="a"),
        build_experiment_identity(brief_path=brief, provider_configs={"primary": config}, seed=13, browsers=("chromium",), git_sha="b"),
    ]
    assert all(row["experiment_fingerprint"] != base for row in variants)


def test_identity_artifact_round_trips(tmp_path):
    brief = tmp_path / "brief.json"
    config = tmp_path / "providers.json"
    brief.write_text('{}\n')
    config.write_text('[]\n')
    output = tmp_path / "experiment-identity.json"
    payload = write_experiment_identity(
        output,
        brief_path=brief,
        provider_configs={"primary": config},
        seed=9,
        browsers=("chromium",),
        git_sha="deadbeef",
    )
    assert json.loads(output.read_text()) == payload
