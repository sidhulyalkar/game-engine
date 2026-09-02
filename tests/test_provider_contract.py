import io
import json
import urllib.error

from game_engine.config import ProviderSpec
from game_engine.providers.openai_compatible import CompletionText, OpenAICompatibleClient, _compact_error_body


def _client(**kwargs):
    values = {
        "name": "test",
        "model": "model",
        "base_url": "https://example.test/v1",
        "api_key_env": "KEY",
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 1024,
        "retries": 0,
    }
    values.update(kwargs)
    return OpenAICompatibleClient(**values)


def test_top_p_null_is_omitted_not_serialized_as_null():
    client = _client(top_p=None, extra_body={"reasoning_effort": "low"})
    payload = json.loads(client._payload("system", "prompt"))
    assert "top_p" not in payload
    assert payload["temperature"] == 1.0
    assert payload["reasoning_effort"] == "low"


def test_normal_provider_keeps_explicit_top_p():
    payload = json.loads(_client(top_p=0.95)._payload("system", "prompt"))
    assert payload["top_p"] == 0.95


def test_provider_spec_accepts_null_top_p_and_rejects_invalid_value():
    spec = ProviderSpec.from_dict({
        "name": "kimi",
        "model": "moonshotai/kimi-k3",
        "base_url": "https://example.test/v1",
        "api_key_env": "KEY",
        "roles": [],
        "top_p": None,
    })
    assert spec.top_p is None

    try:
        ProviderSpec.from_dict({
            "name": "bad",
            "model": "model",
            "base_url": "https://example.test/v1",
            "api_key_env": "KEY",
            "roles": [],
            "top_p": 1.5,
        })
    except ValueError as exc:
        assert "top_p" in str(exc)
    else:
        raise AssertionError("invalid top_p should fail")


def test_completion_text_remains_string_compatible_with_metadata():
    value = CompletionText("<html></html>", {"finish_reason": "stop", "usage": {"completion_tokens": 12}})
    assert isinstance(value, str)
    assert value.startswith("<html")
    assert value.completion_metadata["finish_reason"] == "stop"
    assert value.completion_metadata["usage"]["completion_tokens"] == 12


def test_http_error_body_is_bounded_and_preserved_for_diagnosis():
    body = b'{"detail":"top_p is not a supported parameter for this model"}'
    exc = urllib.error.HTTPError(
        "https://example.test/v1/chat/completions",
        400,
        "Bad Request",
        hdrs={},
        fp=io.BytesIO(body),
    )
    detail = _compact_error_body(exc)
    assert "top_p" in detail
    assert "supported parameter" in detail
