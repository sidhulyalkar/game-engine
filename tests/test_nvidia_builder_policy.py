import json
from pathlib import Path


def test_kimi_builder_uses_supported_low_reasoning_envelope_after_timeout_history():
    providers = {
        row["name"]: row
        for row in json.loads(Path("studio.nvidia.build.json").read_text())["providers"]
    }
    kimi = providers["nvidia-kimi-builder"]
    assert kimi["model"] == "moonshotai/kimi-k3"
    assert kimi["temperature"] == 1.0
    assert kimi["top_p"] is None
    assert kimi["extra_body"] == {"reasoning_effort": "low"}
    assert kimi["retries"] == 0
    assert kimi["max_concurrency"] == 1


def test_nemotron_builder_retains_nonreasoning_profile_that_has_live_survivors():
    providers = {
        row["name"]: row
        for row in json.loads(Path("studio.nvidia.build.json").read_text())["providers"]
    }
    nemotron = providers["nvidia-nemotron-builder"]
    assert nemotron["extra_body"] == {"reasoning_effort": "none"}
    assert nemotron["max_tokens"] == 16384
    assert nemotron["retries"] == 1
