import io
import json
import urllib.error
import urllib.request

import pytest

from game_engine.providers.openai_compatible import OpenAICompatibleClient


def client(**kwargs):
    return OpenAICompatibleClient(
        name="test",
        model="model",
        base_url="https://example.test/v1",
        api_key_env="TEST_PROVIDER_KEY",
        retries=0,
        **kwargs,
    )


def test_payload_can_omit_model_fixed_top_p():
    payload = json.loads(client(top_p=None)._payload("system", "prompt"))
    assert "top_p" not in payload
    assert payload["temperature"] == 0.9


def test_http_error_preserves_bounded_provider_body(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")

    def fail(_request, timeout):
        assert timeout == 180
        raise urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            400,
            "Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"detail":"top_p is fixed and must not be supplied"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError) as exc_info:
        client().complete("system", "prompt")
    message = str(exc_info.value)
    assert "Provider HTTP 400" in message
    assert "top_p is fixed" in message
    assert "secret" not in message


def test_completion_metadata_preserves_finish_reason_and_usage(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")
    body = json.dumps({
        "choices": [{
            "finish_reason": "length",
            "message": {"content": "<!doctype html><html>"},
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda _request, timeout: Response())
    result = client().complete_with_metadata("system", "prompt")
    assert result.content == "<!doctype html><html>"
    assert result.finish_reason == "length"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 20}
