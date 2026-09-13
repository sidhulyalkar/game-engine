from __future__ import annotations

import threading


class ProviderCircuitOpen(RuntimeError):
    pass


def classify_provider_failure(exc: Exception) -> str | None:
    """Classify provider failures that should influence future network spend.

    Response/content parsing remains outside the operational circuit. A provider that
    returned bytes should not be disabled merely because those bytes were malformed.
    Request-contract failures are different: the exact same request shape will fail
    deterministically, so repeating it is wasted spend.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if (
        ("http 400" in text or "http 422" in text)
        and any(token in text for token in ("validation", "immutable", "invalid parameter", "must be"))
    ):
        return "request_contract"
    if "http 429" in text or "rate limit" in text:
        return "rate_limit"
    if "http 404" in text or "model not found" in text:
        return "endpoint_or_model_not_found"
    if "http 5" in text:
        return "server_5xx"
    if "transport failure" in text or "timeout" in text or "urlerror" in text or "connection" in text:
        return "transport"
    return None


class ProviderCircuit:
    """Thread-safe operational circuit reusable across adjacent tournament stages."""

    def __init__(self, provider: str):
        self.provider = provider
        self._lock = threading.Lock()
        self._consecutive = 0
        self._open = False
        self._reason: str | None = None

    def assert_closed(self) -> None:
        with self._lock:
            if self._open:
                raise ProviderCircuitOpen(
                    f"provider circuit open for {self.provider}: {self._reason or 'operational failures'}"
                )

    def record_success(self) -> None:
        with self._lock:
            self._consecutive = 0

    def record_failure(self, exc: Exception) -> str | None:
        failure_class = classify_provider_failure(exc)
        if failure_class is None:
            return None
        with self._lock:
            self._consecutive += 1
            immediate = failure_class in {
                "request_contract",
                "rate_limit",
                "endpoint_or_model_not_found",
            }
            if immediate or self._consecutive >= 2:
                self._open = True
                self._reason = failure_class
        return failure_class

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason
