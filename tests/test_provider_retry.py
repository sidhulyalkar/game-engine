import urllib.error
from email.message import Message

from game_engine.providers.openai_compatible import _retry_delay


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test", code, "failure", headers, None)


def test_retry_after_header_takes_precedence():
    assert _retry_delay(http_error(429, "17"), 0) == 17


def test_rate_limit_backoff_is_not_immediate_retry():
    assert _retry_delay(http_error(429), 0) == 8
    assert _retry_delay(http_error(429), 1) == 16


def test_service_error_and_transport_backoff_are_bounded():
    assert _retry_delay(http_error(503), 0) == 4
    assert _retry_delay(http_error(503), 2) == 16
    assert _retry_delay(TimeoutError(), 0) == 2
    assert _retry_delay(TimeoutError(), 5) == 12
