from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .reality import discover_builds


@dataclass(frozen=True, slots=True)
class BrowserStagePlan:
    reference_browser: str
    promotion_browsers: tuple[str, ...]
    final_browsers: tuple[str, ...]


def plan_browser_stages(browsers: Iterable[str]) -> BrowserStagePlan:
    """Choose one cheap reference engine, deferring the rest until gameplay qualifies."""
    ordered: list[str] = []
    for value in browsers:
        name = str(value).strip()
        if name and name not in ordered:
            ordered.append(name)
    if not ordered:
        raise ValueError("at least one browser is required")
    reference = "chromium" if "chromium" in ordered else ordered[0]
    promotion = tuple(name for name in ordered if name != reference)
    return BrowserStagePlan(
        reference_browser=reference,
        promotion_browsers=promotion,
        final_browsers=tuple(ordered),
    )


def write_build_view(
    source_root: Path,
    output_root: Path,
    allowed_build_ids: Iterable[str],
) -> dict:
    """Create a self-contained evaluator view containing only promoted builds.

    Copying the tiny game source makes the evidence artifact portable after Actions
    extraction and prevents a later evaluator from accidentally rediscovering a
    sibling that failed an earlier gate.
    """
    allowed = sorted({str(value) for value in allowed_build_ids})
    if not allowed:
        raise ValueError("promotion build view requires at least one allowed build")

    discovered = {str(row["build_id"]): row for row in discover_builds(source_root)}
    missing = sorted(set(allowed) - set(discovered))
    if missing:
        raise ValueError(f"promotion build ids not present in source field: {missing}")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    sources_root = output_root / "sources"
    sources_root.mkdir()

    rows = []
    for build_id in allowed:
        source = discovered[build_id]
        src_dir = Path(source["resolved_source_dir"])
        dest_dir = sources_root / build_id
        shutil.copytree(src_dir, dest_dir)
        row = {
            key: value
            for key, value in source.items()
            if key != "resolved_source_dir"
        }
        row["source_dir"] = str(dest_dir)
        rows.append(row)

    spec_path = source_root / "game-spec.json"
    if not spec_path.exists():
        raise ValueError(f"missing GameSpec for promotion view: {spec_path}")
    (output_root / "game-spec.json").write_text(spec_path.read_text())
    (output_root / "builds.json").write_text(json.dumps(rows, indent=2) + "\n")

    manifest = {
        "source_root": str(source_root),
        "allowed_build_ids": allowed,
        "build_count": len(rows),
        "self_contained_sources": True,
    }
    (output_root / "promotion-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
