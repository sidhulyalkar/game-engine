from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .packaging import package_game
from .providers.base import LLMClient
from .schema import Brief, Concept
from .swarm import _extract_json


@dataclass(slots=True)
class PrototypeResult:
    provider: str
    build_id: str
    ok: bool
    source_dir: str | None
    zip_path: str | None
    compressed_bytes: int | None
    byte_headroom: int | None
    warnings: list[str]
    error: str | None = None


def builder_prompt(brief: Brief, concept: Concept) -> tuple[str, str]:
    system = """You are the implementation engineer in a 13KB web-game studio. Build the smallest genuinely playable expression of the supplied mechanic. Prefer procedural Canvas/WebAudio and shared state over assets. Correctness, game feel, and readability come before minification. Return JSON only."""
    schema = {
        "index_html": "complete standalone HTML document as a string",
        "design_notes": ["short note"],
    }
    user = f"""BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nCHAMPION CONCEPT:\n{json.dumps(concept.to_dict(), indent=2)}\n\nBuild a runnable single-file prototype. Requirements:\n- top-level index.html, no build step\n- no remote images/fonts/audio/scripts\n- Canvas 2D and WebAudio are preferred\n- controls must be stated on screen in very little text\n- gameplay must begin immediately or with one obvious click/key\n- fast restart\n- preserve the one-sentence core mechanic rather than substituting an easier generic mechanic\n- make the themed subject visually recognizable; do not use plain circles as unicorns unless abstraction is an intentional mechanic\n- movement rates are in pixels/second (or analogous units) and MUST be multiplied by delta-time correctly\n- all spawned entities, particles, trails, timers, and audio nodes must have bounded lifetimes or bounded storage\n- use clear variable names and correct object/property comparisons in the prototype; code-golf happens only after gameplay qualification\n- verify collision, scoring, game-over, and restart logic against the actual variable types you create\n- target substantial headroom under {brief.size_limit_bytes} compressed bytes; this is a prototype, not a last-byte compression pass\n\nReturn exactly this JSON shape, no markdown fences:\n{json.dumps(schema, indent=2)}"""
    return system, user


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value[:60] or "provider"


class PrototypeForge:
    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 4):
        self.clients = clients
        self.max_workers = max_workers

    def build(self, brief: Brief, concept: Concept, output_dir: Path) -> list[PrototypeResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        system, prompt = builder_prompt(brief, concept)
        results: list[PrototypeResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {
                pool.submit(client.complete, system, prompt): (spec, client)
                for spec, client in self.clients
            }
            for future in as_completed(future_map):
                spec, client = future_map[future]
                provider = getattr(spec, "name", getattr(client, "name", "provider"))
                try:
                    payload = _extract_json(future.result())
                    html = payload.get("index_html")
                    if not isinstance(html, str) or "<html" not in html.lower():
                        raise ValueError("provider did not return a complete index_html document")
                    build_id = hashlib.sha1(f"{provider}:{concept.concept_id}:{html}".encode()).hexdigest()[:10]
                    build_dir = output_dir / f"{_safe_name(provider)}-{build_id}"
                    build_dir.mkdir(parents=True, exist_ok=True)
                    (build_dir / "index.html").write_text(html)
                    (build_dir / "model-notes.json").write_text(json.dumps({
                        "provider": provider,
                        "concept_id": concept.concept_id,
                        "design_notes": payload.get("design_notes", []),
                    }, indent=2) + "\n")
                    zip_path = output_dir / "dist" / f"{_safe_name(provider)}-{build_id}.zip"
                    report = package_game(build_dir, zip_path, brief.size_limit_bytes)
                    warnings = list(report.warnings)
                    if "<canvas" not in html.lower():
                        warnings.append("No canvas element detected; verify rendering strategy intentionally.")
                    results.append(PrototypeResult(
                        provider=provider,
                        build_id=build_id,
                        ok=report.ok,
                        source_dir=str(build_dir),
                        zip_path=str(zip_path),
                        compressed_bytes=report.compressed_bytes,
                        byte_headroom=brief.size_limit_bytes - report.compressed_bytes,
                        warnings=warnings,
                    ))
                except Exception as exc:
                    results.append(PrototypeResult(
                        provider=provider,
                        build_id="failed",
                        ok=False,
                        source_dir=None,
                        zip_path=None,
                        compressed_bytes=None,
                        byte_headroom=None,
                        warnings=[],
                        error=f"{type(exc).__name__}: {exc}",
                    ))

        results.sort(key=lambda r: (not r.ok, -(r.byte_headroom or -10**9), r.provider))
        (output_dir / "builds.json").write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
        return results
