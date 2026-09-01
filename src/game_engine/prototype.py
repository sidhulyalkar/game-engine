from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .game_spec import compile_game_spec
from .packaging import package_game
from .providers.base import LLMClient
from .schema import Brief, Concept, GameSpec
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
    raw_response_path: str | None = None
    response_format: str | None = None
    game_spec_path: str | None = None
    error: str | None = None


def builder_prompt(brief: Brief, spec: GameSpec) -> tuple[str, str]:
    system = """You are the implementation engineer in a 13KB web-game studio. Build the smallest genuinely playable expression of the supplied GameSpec. Correctness, game feel, and readability come before code golf. Return ONLY the complete standalone HTML document. Do not return JSON, markdown fences, explanations, or design notes."""
    telemetry_shape = {
        "schema_version": "0.1",
        "snapshot": "function returning snapshot object",
        "events": "function returning recent event objects",
        "snapshot_fields": [
            "elapsed_ms", "tick", "state", "alive", "game_over", "score", "progress",
            "restart_count", "entity_count", "action_count", "last_action_ms",
            "core_mechanic_activations", "progression_transitions", "state_hash",
        ],
        "event_shape": {"type": "event name", "at_ms": "elapsed game milliseconds"},
    }
    user = f"""COMPETITION BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\nIMPLEMENTATION GAMESPEC:\n{json.dumps(spec.to_dict(), indent=2)}\n\nDEVELOPMENT TELEMETRY CONTRACT:\n{json.dumps(telemetry_shape, indent=2)}\n\nBuild exactly one runnable single-file prototype. Requirements:\n- response begins with <!doctype html> or <html and ends with </html>\n- top-level index.html semantics, no build step\n- no remote images/fonts/audio/scripts/network dependency\n- implement the PRIMARY CATEGORY only; every GameSpec non-goal stays out\n- Canvas 2D and WebAudio are preferred\n- controls are stated on screen in very little text\n- gameplay begins immediately or with one obvious click/key\n- fast coherent restart\n- preserve the GameSpec interaction invariant rather than substituting an easier generic mechanic\n- make the themed subject visually recognizable; avoid placeholder circles unless abstraction is itself the design\n- use a fixed 60 Hz simulation or delta-time in SECONDS for every rate; damping/decay must be frame-rate independent\n- clamp pathological frame delta to <= {spec.timing_contract.get('max_frame_dt_seconds', 0.05)} seconds\n- all spawned entities, particles, trails, timers, arrays, and audio nodes must obey the GameSpec bounds\n- use readable prototype code and correct object/property comparisons; code golf happens later\n- verify collision, scoring/progress, death/win, and restart against the actual variable types you create\n- implement only the one-arena playable slice; do not spend tokens on multiple levels, networking, persistence, menus, or meta systems\n- target substantial headroom under {brief.size_limit_bytes} compressed bytes\n\nTelemetry is REQUIRED in this development prototype:\n- expose `window.__GAME_ENGINE_TELEMETRY__` with `schema_version: '0.1'`, `snapshot()` and `events()`\n- `snapshot()` returns every listed snapshot field; use null only when a field truly has no value\n- `state` uses `playing`, `dead`, or `won`; `progress` is normalized 0..1\n- `entity_count` counts active gameplay entities/particles/trails that can grow over time\n- `action_count` increments only when a player input is accepted by gameplay; `last_action_ms` records that elapsed game time\n- `core_mechanic_activations` increments when the defining GameSpec interaction actually occurs, not on every key press\n- `progression_transitions` increments when difficulty/rule progression changes\n- `state_hash` is a compact deterministic string derived from meaningful gameplay state; DO NOT include wall-clock/elapsed time alone\n- keep a bounded event log (max 256 recent events) containing at least `run_start`, `action_accepted`, `progress_change`, `damage_or_death`, `restart`, `core_mechanic_activation`, and `progression_transition` when those events occur\n- each event is `{type, at_ms}`; telemetry must not alter gameplay when read\n- this telemetry is evidence instrumentation, not player-facing UI\n\nOutput HTML only."""
    return system, user


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value[:60] or "provider"


def _extract_html_response(text: str) -> tuple[str, str]:
    """Accept HTML-native output plus legacy JSON/fenced responses.

    Large HTML inside JSON is fragile because every quote/newline must be escaped. The
    current builder protocol therefore asks for raw HTML, while this parser preserves
    compatibility and salvages common provider formatting drift.
    """
    raw = text.strip().lstrip("\ufeff")
    if not raw:
        raise ValueError("provider returned an empty response")

    # Backward compatibility with the v0.1 JSON builder protocol.
    if raw.startswith("{"):
        try:
            payload = _extract_json(raw)
            html = payload.get("index_html")
            if isinstance(html, str) and "<html" in html.lower():
                return html.strip(), "legacy-json"
        except Exception:
            # Fall through and try to salvage an HTML document embedded in otherwise
            # malformed wrapper text.
            pass

    fenced = re.match(r"^```(?:html)?\s*(.*?)\s*```$", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
        format_name = "fenced-html"
    else:
        format_name = "raw-html"

    lower = raw.lower()
    starts = [pos for pos in (lower.find("<!doctype html"), lower.find("<html")) if pos >= 0]
    if not starts:
        raise ValueError("provider response contains no HTML document")
    start = min(starts)
    end = lower.rfind("</html>")
    if end < start:
        raise ValueError("provider response contains no closing </html>")
    html = raw[start : end + len("</html>")].strip()
    if "<html" not in html.lower():
        raise ValueError("provider did not return a complete HTML document")
    return html, format_name


def _write_raw_response(output_dir: Path, provider: str, text: str) -> Path:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(text.encode()).hexdigest()[:10]
    path = raw_dir / f"{_safe_name(provider)}-{digest}.txt"
    path.write_text(text)
    return path


class PrototypeForge:
    def __init__(self, clients: list[tuple[object, LLMClient]], max_workers: int = 4):
        self.clients = clients
        self.max_workers = max_workers

    def build(self, brief: Brief, concept: Concept, output_dir: Path) -> list[PrototypeResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        spec = compile_game_spec(brief, concept)
        spec_path = output_dir / "game-spec.json"
        spec_path.write_text(json.dumps(spec.to_dict(), indent=2) + "\n")
        system, prompt = builder_prompt(brief, spec)
        results: list[PrototypeResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {
                pool.submit(client.complete, system, prompt): (provider_spec, client)
                for provider_spec, client in self.clients
            }
            for future in as_completed(future_map):
                provider_spec, client = future_map[future]
                provider = getattr(provider_spec, "name", getattr(client, "name", "provider"))
                raw_path: Path | None = None
                try:
                    response = future.result()
                    raw_path = _write_raw_response(output_dir, provider, response)
                    html, response_format = _extract_html_response(response)
                    build_id = hashlib.sha1(
                        f"{provider}:{concept.concept_id}:{spec.spec_version}:{html}".encode()
                    ).hexdigest()[:10]
                    build_dir = output_dir / f"{_safe_name(provider)}-{build_id}"
                    build_dir.mkdir(parents=True, exist_ok=True)
                    (build_dir / "index.html").write_text(html)

                    # Evidence belongs next to the contender, not inside the 13KB game ZIP.
                    meta_dir = output_dir / "meta"
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    meta_path = meta_dir / f"{_safe_name(provider)}-{build_id}.json"
                    meta_path.write_text(json.dumps({
                        "provider": provider,
                        "concept_id": concept.concept_id,
                        "game_spec": str(spec_path),
                        "raw_response": str(raw_path),
                        "response_format": response_format,
                        "telemetry_schema": "0.1",
                    }, indent=2) + "\n")

                    zip_path = output_dir / "dist" / f"{_safe_name(provider)}-{build_id}.zip"
                    report = package_game(build_dir, zip_path, brief.size_limit_bytes)
                    warnings = list(report.warnings)
                    if "<canvas" not in html.lower():
                        warnings.append("No canvas element detected; verify rendering strategy intentionally.")
                    if "__GAME_ENGINE_TELEMETRY__" not in html:
                        warnings.append("Development telemetry API marker not detected; Gameplay Evidence Lab will reject instrumentation.")
                    results.append(PrototypeResult(
                        provider=provider,
                        build_id=build_id,
                        ok=report.ok,
                        source_dir=str(build_dir),
                        zip_path=str(zip_path),
                        compressed_bytes=report.compressed_bytes,
                        byte_headroom=brief.size_limit_bytes - report.compressed_bytes,
                        warnings=warnings,
                        raw_response_path=str(raw_path),
                        response_format=response_format,
                        game_spec_path=str(spec_path),
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
                        raw_response_path=str(raw_path) if raw_path else None,
                        response_format=None,
                        game_spec_path=str(spec_path),
                        error=f"{type(exc).__name__}: {exc}",
                    ))

        results.sort(key=lambda r: (not r.ok, -(r.byte_headroom or -10**9), r.provider))
        (output_dir / "builds.json").write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
        return results
