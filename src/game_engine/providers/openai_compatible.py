from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def _retry_delay(exc: Exception, attempt: int) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return max(1.0, min(60.0, float(retry_after)))
            except ValueError:
                pass
        if exc.code == 429:
            return min(30.0, 8.0 * (2**attempt))
        if 500 <= exc.code < 600:
            return min(20.0, 4.0 * (2**attempt))
    return min(12.0, 2.0 * (2**attempt))


class OpenAICompatibleClient:
    """Dependency-free adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key_env: str,
        timeout: int = 180,
        temperature: float = 0.9,
        top_p: float = 0.95,
        max_tokens: int = 8192,
        retries: int = 3,
        extra_body: dict | None = None,
    ):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.retries = max(0, retries)
        self.extra_body = dict(extra_body or {})

    def _payload(self, system: str, prompt: str) -> bytes:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        payload.update(self.extra_body)
        return json.dumps(payload).encode()

    def complete(self, system: str, prompt: str) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=self._payload(system, prompt),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "game-engine/0.1 autonomous-studio",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read())
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("Provider returned no choices")
                message = choices[0].get("message") or {}
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("Provider returned empty message content")
                return content
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.retries:
                    raise RuntimeError(f"Provider HTTP {exc.code} for model {self.model}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"Provider transport failure for model {self.model}: {type(exc).__name__}") from exc
            if attempt < self.retries and last_error is not None:
                time.sleep(_retry_delay(last_error, attempt))

        raise RuntimeError(f"Provider failed after retries: {type(last_error).__name__}")
