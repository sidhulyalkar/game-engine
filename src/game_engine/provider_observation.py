from __future__ import annotations

from typing import Any


_OBSERVATION_KEY = "_game_engine"


def usage_with_observation(result: object) -> dict[str, Any] | None:
    """Preserve provider usage while attaching measured transport metadata.

    The nested key is intentionally namespaced so provider-native token fields remain
    byte-for-byte interpretable. Missing usage or timing stays missing rather than
    being imputed.
    """
    raw_usage = getattr(result, "usage", None)
    usage: dict[str, Any] = dict(raw_usage) if isinstance(raw_usage, dict) else {}
    observation: dict[str, Any] = {}
    elapsed_ms = getattr(result, "elapsed_ms", None)
    attempt_count = getattr(result, "attempt_count", None)
    if isinstance(elapsed_ms, (int, float)):
        observation["elapsed_ms"] = round(float(elapsed_ms), 3)
    if isinstance(attempt_count, int) and attempt_count >= 1:
        observation["attempt_count"] = attempt_count
        observation["retry_count"] = max(0, attempt_count - 1)
    if observation:
        usage[_OBSERVATION_KEY] = observation
    return usage or None


def exception_observation(exc: Exception) -> dict[str, Any] | None:
    observation: dict[str, Any] = {}
    elapsed_ms = getattr(exc, "elapsed_ms", None)
    attempt_count = getattr(exc, "attempt_count", None)
    if isinstance(elapsed_ms, (int, float)):
        observation["elapsed_ms"] = round(float(elapsed_ms), 3)
    if isinstance(attempt_count, int) and attempt_count >= 1:
        observation["attempt_count"] = attempt_count
        observation["retry_count"] = max(0, attempt_count - 1)
    return observation or None


def observation_from_usage(usage: object) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(_OBSERVATION_KEY)
    return dict(value) if isinstance(value, dict) else None


def provider_token_counts(usage: object) -> dict[str, int] | None:
    """Return only token counts explicitly reported by the provider."""
    if not isinstance(usage, dict):
        return None
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "completion_tokens": ("completion_tokens", "output_tokens"),
        "total_tokens": ("total_tokens",),
    }
    counts: dict[str, int] = {}
    for canonical, keys in aliases.items():
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                counts[canonical] = value
                break
    if "total_tokens" not in counts and "prompt_tokens" in counts and "completion_tokens" in counts:
        counts["total_tokens"] = counts["prompt_tokens"] + counts["completion_tokens"]
    return counts or None
