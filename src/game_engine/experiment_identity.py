from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Iterable

from .version import ENGINE_VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_experiment_identity(
    *,
    brief_path: Path,
    provider_configs: Mapping[str, Path],
    seed: int,
    browsers: Iterable[str],
    git_sha: str | None = None,
) -> dict:
    """Create a stable experiment identity for future cross-run learning.

    Provider performance is non-stationary when prompts, engine code, model configs,
    or the brief change. Those inputs are fingerprinted so historical observations
    can be grouped rather than naively pooled across incompatible experiments.
    """
    if not brief_path.exists():
        raise FileNotFoundError(brief_path)
    configs = {}
    for name, path in sorted(provider_configs.items()):
        if not path.exists():
            raise FileNotFoundError(path)
        configs[str(name)] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    browser_list = []
    for value in browsers:
        name = str(value).strip()
        if name and name not in browser_list:
            browser_list.append(name)
    payload = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "git_sha": git_sha or os.environ.get("GITHUB_SHA") or None,
        "seed": int(seed),
        "brief": {
            "path": str(brief_path),
            "sha256": sha256_file(brief_path),
        },
        "provider_configs": configs,
        "browsers": browser_list,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["experiment_fingerprint"] = hashlib.sha256(canonical).hexdigest()
    return payload


def write_experiment_identity(
    output_path: Path,
    *,
    brief_path: Path,
    provider_configs: Mapping[str, Path],
    seed: int,
    browsers: Iterable[str],
    git_sha: str | None = None,
) -> dict:
    payload = build_experiment_identity(
        brief_path=brief_path,
        provider_configs=provider_configs,
        seed=seed,
        browsers=browsers,
        git_sha=git_sha,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
