from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .reality import discover_builds


@dataclass(slots=True)
class SourceFinding:
    code: str
    severity: str
    evidence: str
    player_impact: str


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def _function_body(source: str, name: str) -> str | None:
    """Extract a classic `function name(...) { ... }` body with light JS lexing."""
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    if not match:
        return None
    start = source.find("{", match.start())
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    i = start
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:i]
        i += 1
    return None


def _fixed_hz(game_spec: dict[str, Any]) -> float | None:
    timing = game_spec.get("timing_contract") or {}
    text = str(timing.get("simulation", ""))
    match = re.search(r"(\d+(?:\.\d+)?)\s*Hz", text, re.I)
    return float(match.group(1)) if match else None


def _representative_max_seconds(game_spec: dict[str, Any]) -> float | None:
    for row in game_spec.get("prototype_scope") or []:
        match = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*second", str(row), re.I)
        if match:
            return float(match.group(2))
    return None


def _intended_escalation_seconds(game_spec: dict[str, Any]) -> float | None:
    text = " ".join([
        str(game_spec.get("interaction_invariant", "")),
        str(game_spec.get("player_goal", "")),
        *(str(row) for row in game_spec.get("core_loop") or []),
    ]).lower()
    for token in re.findall(r"after\s+([a-z]+|\d+(?:\.\d+)?)\s+seconds?", text):
        if token in _NUMBER_WORDS:
            return float(_NUMBER_WORDS[token])
        try:
            return float(token)
        except ValueError:
            continue
    return None


def _timer_counter_cycles(source: str) -> list[dict[str, float | str]]:
    """Infer simple nested timer->counter escalation cycles."""
    results: list[dict[str, float | str]] = []
    accumulation = re.compile(r"(?P<ref>(?:[A-Za-z_$]\w*\.)*[A-Za-z_$]\w*)\s*\+=\s*(?:delta|dt)\s*;")
    for match in accumulation.finditer(source):
        timer_ref = match.group("ref")
        threshold = re.search(
            rf"if\s*\(\s*{re.escape(timer_ref)}\s*>=\s*(\d+(?:\.\d+)?)\s*\)",
            source[match.end():match.end() + 700],
        )
        if not threshold:
            continue
        timer_seconds = float(threshold.group(1))
        threshold_end = match.end() + threshold.end()
        segment = source[threshold_end:threshold_end + 1200]
        counter_match = re.search(
            r"(?P<ref>(?:[A-Za-z_$]\w*\.)*[A-Za-z_$]\w*)\s*=\s*Math\.min\(\s*[^,]+,\s*(?P=ref)\s*\+\s*(?P<step>\d+(?:\.\d+)?)\s*\)",
            segment,
        )
        if counter_match is None:
            counter_match = re.search(
                r"(?P<ref>(?:[A-Za-z_$]\w*\.)*[A-Za-z_$]\w*)\s*\+=\s*(?P<step>\d+(?:\.\d+)?)\s*;",
                segment,
            )
        if counter_match is None:
            continue
        counter_ref = counter_match.group("ref")
        step = float(counter_match.group("step"))
        if step <= 0:
            continue
        counter_threshold = re.search(
            rf"if\s*\(\s*{re.escape(counter_ref)}\s*>=\s*(\d+(?:\.\d+)?)\s*\)",
            segment[counter_match.end():],
        )
        if not counter_threshold:
            continue
        target = float(counter_threshold.group(1))
        results.append({
            "timer": timer_ref,
            "counter": counter_ref,
            "timer_seconds": timer_seconds,
            "counter_target": target,
            "counter_step": step,
            "estimated_seconds": timer_seconds * math.ceil(target / step),
        })
    return results


def _hazard_lifetime_travel(source: str, hz: float | None) -> list[dict[str, float]]:
    if not hz or hz <= 0:
        return []
    pattern = re.compile(
        r"vx\s*:\s*[^,\n]*?\*\s*(?P<vx>\d+(?:\.\d+)?)\s*,\s*"
        r"vy\s*:\s*[^,\n]*?\*\s*(?P<vy>\d+(?:\.\d+)?)\s*,"
        r"(?P<middle>[\s\S]{0,180}?)life\s*:\s*(?P<life>\d+(?:\.\d+)?)",
        re.I,
    )
    rows: list[dict[str, float]] = []
    for match in pattern.finditer(source):
        middle = match.group("middle")
        radius_match = re.search(r"radius\s*:\s*(\d+(?:\.\d+)?)", middle, re.I)
        radius = float(radius_match.group(1)) if radius_match else 0.0
        vx = float(match.group("vx"))
        vy = float(match.group("vy"))
        life_frames = float(match.group("life"))
        lifetime_seconds = life_frames / hz
        speed_upper = math.hypot(vx, vy)
        rows.append({
            "radius": radius,
            "life_frames": life_frames,
            "lifetime_seconds": lifetime_seconds,
            "speed_upper_px_s": speed_upper,
            "travel_upper_px": speed_upper * lifetime_seconds,
        })
    return rows


def _seed_declaration(source: str) -> tuple[str, str] | None:
    match = re.search(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*seed[\w$]*)\s*=\s*([^;\n]+)",
        source,
        re.I,
    )
    return (match.group(1), match.group(2).strip()) if match else None


def _rng_state_is_constant(source: str) -> tuple[bool, str | None]:
    declaration = _seed_declaration(source)
    body = _function_body(source, "rng")
    if declaration is None or body is None:
        return False, None
    name, _ = declaration
    if not re.search(rf"\b{re.escape(name)}\b", body):
        return False, None
    mutation = re.search(
        rf"\b{re.escape(name)}\s*(?:=|\+=|-=|\*=|/=|%=|\+\+|--)",
        body,
    )
    return mutation is None, name


def _restart_spawns_duplicate_raf(source: str, loop_body: str | None) -> str | None:
    if not loop_body:
        return None
    # A loop that always schedules its successor is already alive during ordinary
    # restart input. A restart/start function that also schedules loop creates a
    # second RAF chain. Conditional `if(playing) requestAnimationFrame(loop)` loops
    # are excluded because a stopped chain may legitimately need resuming.
    unconditional = re.search(
        r"(?:^|[;{}]\s*)requestAnimationFrame\s*\(\s*loop\s*\)\s*;",
        loop_body,
    )
    if not unconditional:
        return None
    for name in ("start", "reset", "restart"):
        body = _function_body(source, name)
        if not body or not re.search(r"requestAnimationFrame\s*\(\s*loop\s*\)", body):
            continue
        handler = re.search(
            rf"addEventListener\s*\([^\n;]*[\s\S]{{0,420}}?\b{re.escape(name)}\s*\(\s*\)",
            source,
        )
        if handler:
            return name
    return None


def analyze_source(html: str, game_spec: dict[str, Any]) -> dict[str, Any]:
    findings: list[SourceFinding] = []
    timing = game_spec.get("timing_contract") or {}
    deterministic = bool(timing.get("deterministic_seed"))

    if deterministic and re.search(r"\bMath\.random\s*\(", html):
        findings.append(SourceFinding(
            code="nondeterministic_rng",
            severity="blocker",
            evidence="GameSpec requires deterministic_seed but source calls Math.random().",
            player_impact="Replays, debugging, and cross-run evidence cannot reproduce the same game state.",
        ))

    seed_decl = _seed_declaration(html)
    if deterministic and seed_decl and re.search(r"\b(?:Date\.now|performance\.now)\s*\(", seed_decl[1]):
        findings.append(SourceFinding(
            code="wall_clock_seed",
            severity="blocker",
            evidence=f"GameSpec requires deterministic_seed but {seed_decl[0]} is initialized from wall-clock time.",
            player_impact="Identical runs can start from different random states, invalidating replay and cross-run comparisons.",
        ))

    constant_rng, constant_seed_name = _rng_state_is_constant(html)
    if constant_rng:
        findings.append(SourceFinding(
            code="constant_prng_state",
            severity="major",
            evidence=f"rng() reads {constant_seed_name} but never mutates that PRNG state.",
            player_impact="Every RNG call can return the same value, collapsing intended spawn/visual variation.",
        ))

    if game_spec.get("telemetry_contract") and "__GAME_ENGINE_TELEMETRY__" not in html:
        findings.append(SourceFinding(
            code="missing_telemetry_contract",
            severity="blocker",
            evidence="GameSpec declares telemetry_contract but source exposes no __GAME_ENGINE_TELEMETRY__ API.",
            player_impact="The engine cannot independently measure agency, progression, restart, or boundedness.",
        ))

    loop_body = _function_body(html, "loop")
    if timing.get("max_frame_dt_seconds") is not None and loop_body:
        acc_match = re.search(r"\b(?:[A-Za-z_$]\w*\.)*acc\s*\+=\s*(?:delta|dt)\b", loop_body)
        if acc_match:
            prefix = loop_body[:acc_match.start()]
            clamped = bool(
                re.search(r"\b(?:delta|dt)\s*=\s*Math\.min\s*\(", prefix)
                or re.search(r"if\s*\(\s*(?:delta|dt)\s*>[^)]*\)[^{;]*(?:delta|dt)\s*=", prefix)
            )
            if not clamped:
                findings.append(SourceFinding(
                    code="uncapped_accumulator_dt",
                    severity="major",
                    evidence="Frame delta is added to the fixed-step accumulator before any max-frame-dt clamp.",
                    player_impact="A long frame can trigger a large catch-up burst and destabilize pacing/physics.",
                ))

    reset_body = _function_body(html, "reset") or ""
    if loop_body and re.search(r"if\s*\([^)]*playing[^)]*\)\s*requestAnimationFrame\s*\(\s*loop\s*\)", loop_body):
        restart_handler = re.search(
            r"addEventListener\s*\(\s*['\"](?:click|pointerdown|keydown)['\"][\s\S]{0,320}?reset\s*\(\s*\)",
            html,
        )
        if restart_handler and "requestAnimationFrame" not in reset_body:
            handler_text = html[restart_handler.start():restart_handler.end() + 180]
            if "requestAnimationFrame" not in handler_text:
                findings.append(SourceFinding(
                    code="restart_loop_not_resumed",
                    severity="blocker",
                    evidence="Main loop stops scheduling RAF when playing=false, but reset/restart does not schedule loop again.",
                    player_impact="The UI can claim restart while the simulation remains frozen after death.",
                ))

    duplicate_restart = _restart_spawns_duplicate_raf(html, loop_body)
    if duplicate_restart:
        findings.append(SourceFinding(
            code="restart_spawns_duplicate_raf",
            severity="blocker",
            evidence=f"loop() schedules RAF unconditionally and {duplicate_restart}() schedules loop again from player restart input.",
            player_impact="Each restart can add another simulation loop, multiplying game speed and update side effects.",
        ))

    run_max = _representative_max_seconds(game_spec)
    intended = _intended_escalation_seconds(game_spec)
    for cycle in _timer_counter_cycles(html):
        estimated = float(cycle["estimated_seconds"])
        if run_max is not None and estimated > run_max:
            findings.append(SourceFinding(
                code="escalation_after_representative_run",
                severity="blocker",
                evidence=(
                    f"Nested {cycle['timer']}->{cycle['counter']} cycle estimates first escalation at "
                    f"{estimated:.1f}s, beyond the {run_max:.1f}s representative-run ceiling."
                ),
                player_impact="The promised escalation may never appear during the prototype's intended play session.",
            ))
        elif intended is not None and estimated > intended * 2:
            findings.append(SourceFinding(
                code="escalation_contract_drift",
                severity="major",
                evidence=f"Source escalation estimates {estimated:.1f}s versus ~{intended:.1f}s promised by GameSpec.",
                player_impact="The central risk loop arrives far later than the design contract communicates.",
            ))

    hz = _fixed_hz(game_spec)
    if re.search(r"\.life\s*--", html) and re.search(r"\.x\s*\+=\s*[^;]*\*\s*(?:delta|dt)", html):
        for row in _hazard_lifetime_travel(html, hz):
            if row["radius"] > 0 and row["travel_upper_px"] < row["radius"]:
                findings.append(SourceFinding(
                    code="hazard_travel_below_own_radius",
                    severity="major",
                    evidence=(
                        f"Hazard upper-bound travel is {row['travel_upper_px']:.2f}px over "
                        f"{row['lifetime_seconds']:.2f}s, below its {row['radius']:.2f}px radius."
                    ),
                    player_impact="The hazard can expire before moving enough to create meaningful spatial pressure.",
                ))

    blockers = sum(row.severity == "blocker" for row in findings)
    majors = sum(row.severity == "major" for row in findings)
    return {
        "qualified": blockers == 0,
        "blockers": blockers,
        "majors": majors,
        "finding_count": len(findings),
        "findings": [asdict(row) for row in findings],
    }


def _browser_qualified_ids(reality_root: Path | None) -> set[str] | None:
    if reality_root is None:
        return None
    path = reality_root / "qualification.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return {str(value) for value in payload.get("full_pass_build_ids", [])}


class SourceFalsificationLab:
    def run(
        self,
        builds_root: Path,
        output_dir: Path,
        reality_root: Path | None = None,
    ) -> dict[str, Any]:
        builds = discover_builds(builds_root)
        allowed = _browser_qualified_ids(reality_root)
        if allowed is not None:
            builds = [row for row in builds if str(row.get("build_id")) in allowed]
        if not builds:
            raise ValueError("no eligible browser-qualified builds found for source falsification")

        spec_path = builds_root / "game-spec.json"
        if not spec_path.exists():
            raise ValueError(f"missing GameSpec for source falsification: {spec_path}")
        game_spec = json.loads(spec_path.read_text())
        output_dir.mkdir(parents=True, exist_ok=True)

        rows = []
        for build in builds:
            html = (Path(build["resolved_source_dir"]) / "index.html").read_text()
            report = analyze_source(html, game_spec)
            rows.append({
                "build_id": str(build.get("build_id")),
                "provider": str(build.get("provider", "unknown")),
                **report,
            })

        qualified = [row["build_id"] for row in rows if row["qualified"]]
        blocked = [row["build_id"] for row in rows if not row["qualified"]]
        result = {
            "builds_analyzed": len(rows),
            "full_pass_build_ids": qualified,
            "blocked_build_ids": blocked,
            "rows": rows,
        }
        (output_dir / "source-falsification.json").write_text(json.dumps(rows, indent=2) + "\n")
        (output_dir / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
