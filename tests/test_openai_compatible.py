import io
import json
import urllib.error
import urllib.request

import pytest

from game_engine.providers.openai_compatible import OpenAICompatibleClient


def client(**kwargs):
    retries = kwargs.pop("retries", 0)
    return OpenAICompatibleClient(
        name="test",
        model="model",
        base_url="https://example.test/v1",
        api_key_env="TEST_PROVIDER_KEY",
        retries=retries,
        **kwargs,
    )


def test_payload_can_omit_model_fixed_top_p():
    payload = json.loads(client(top_p=None)._payload("system", "prompt"))
    assert "top_p" not in payload
    assert payload["temperature"] == 0.9


def test_http_error_preserves_bounded_provider_body_and_observation(monkeypatch):
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
    assert exc_info.value.attempt_count == 1
    assert exc_info.value.elapsed_ms >= 0


def test_completion_metadata_preserves_finish_reason_usage_and_observation(monkeypatch):
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
    assert result.attempt_count == 1
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0


def test_retry_observation_counts_actual_attempts(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")
    calls = 0
    body = json.dumps({
        "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
        "usage": {"total_tokens": 7},
    }).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    def flaky(_request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://example.test/v1/chat/completions",
                503,
                "Service Unavailable",
                hdrs={},
                fp=io.BytesIO(b"temporary"),
            )
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    monkeypatch.setattr("game_engine.providers.openai_compatible.time.sleep", lambda _seconds: None)
    result = client(retries=1).complete_with_metadata("system", "prompt")
    assert calls == 2
    assert result.attempt_count == 2
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
