from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


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


def _compact_error_body(exc: urllib.error.HTTPError, limit: int = 1200) -> str | None:
    """Return a bounded diagnostic body without exposing request credentials."""
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    if not body:
        return None
    body = " ".join(body.split())
    return body[:limit] + ("…" if len(body) > limit else "")


class CompletionText(str):
    """String-compatible provider output with non-invasive completion provenance."""

    def __new__(cls, content: str, metadata: dict[str, Any] | None = None):
        obj = super().__new__(cls, content)
        obj.completion_metadata = dict(metadata or {})
        return obj


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
        top_p: float | None = 0.95,
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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        # Some OpenAI-compatible models expose temperature but explicitly fix top_p.
        # `null` in provider config means omit the parameter entirely rather than
        # sending JSON null to an endpoint that may reject the field.
        if self.top_p is not None:
            payload["top_p"] = self.top_p
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
                "User-Agent": "game-engine/0.2 autonomous-studio",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    data = json.loads(raw)
                    response_status = getattr(response, "status", 200)
                    response_headers = getattr(response, "headers", None)
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("Provider returned no choices")
                choice = choices[0] or {}
                message = choice.get("message") or {}
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("Provider returned empty message content")
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
                request_id = None
                if response_headers is not None:
                    for header in ("x-request-id", "request-id", "x-nvidia-request-id"):
                        value = response_headers.get(header)
                        if value:
                            request_id = str(value)
                            break
                metadata = {
                    "model": data.get("model") or self.model,
                    "http_status": response_status,
                    "finish_reason": choice.get("finish_reason"),
                    "usage": usage,
                    "request_id": request_id,
                    "content_chars": len(content),
                    "reasoning_chars": len(message.get("reasoning_content") or "")
                    if isinstance(message.get("reasoning_content"), str)
                    else 0,
                }
                return CompletionText(content, metadata)
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.retries:
                    detail = _compact_error_body(exc)
                    suffix = f": {detail}" if detail else ""
                    raise RuntimeError(f"Provider HTTP {exc.code} for model {self.model}{suffix}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"Provider transport failure for model {self.model}: {type(exc).__name__}") from exc
            if attempt < self.retries and last_error is not None:
                time.sleep(_retry_delay(last_error, attempt))

        raise RuntimeError(f"Provider failed after retries: {type(last_error).__name__}")
