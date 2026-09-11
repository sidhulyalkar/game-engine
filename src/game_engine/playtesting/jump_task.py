"""Exploratory transfer from motor acceptance to real collision-world landings."""
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import tempfile

from .runner import RESOURCES, execute, source_manifest
from .scenario import digest
from .timing import write_json

SCOPE = "authored_gap_game_session"


def protocol():
    schedule = [{"id": f"{gap}-{arm}-{offset}-{repeat}", "gap": gap, "arm": arm,
                 "offset_ticks": offset, "repeat": repeat}
                for gap in (2, 4, 6, 8) for arm in ("default", "narrow")
                for offset in range(-1, 25) for repeat in range(2)]
    random.Random(2028).shuffle(schedule)
    return {"version": 1, "scope": SCOPE, "tick_hz": 120, "horizon_ticks": 240,
            "gap_widths": [2, 4, 6, 8], "schedule": schedule,
            "hypothesis": "Default coyote time increases far-platform landings for some delayed inputs relative to a half-tick window.",
            "study_kind": "exploratory_fixture_transfer",
            "primary_endpoint": "grounded_on_target_before_first_death",
            "implementation_sha256": digest({n: hashlib.sha256((RESOURCES/n).read_bytes()).hexdigest()
                                               for n in ("PumaJumpHost.cs", "jump_task.py")})}


def make_jump_plan(source):
    p = dict(protocol(), source=source_manifest(Path(source), "puma-platformer"))
    return {"plan": p, "plan_sha256": digest(p)}


def validate_plan(envelope):
    if set(envelope) != {"plan", "plan_sha256"} or digest(envelope["plan"]) != envelope["plan_sha256"]:
        raise ValueError("Plan fingerprint mismatch")
    p = envelope["plan"]
    if {k: v for k, v in p.items() if k != "source"} != protocol():
        raise ValueError("Unsupported or changed gap protocol")
    if set(p["source"]) != {"files", "sha256"} or digest(p["source"]["files"]) != p["source"]["sha256"]:
        raise ValueError("Source manifest mismatch")
    return p


def measurements(rows, gap, press, horizon):
    if not isinstance(rows, list) or not 1 <= len(rows) <= horizon:
        raise ValueError("Missing or excessive trace steps")
    departure = None; grounded_seen = False; landing = None; jumps = []; wall_kicks = []
    for tick, row in enumerate(rows, 1):
        if (set(row) != {"tick", "x", "y", "grounded", "ground_index", "events", "deaths", "jump_pressed"}
                or type(row["tick"]) is not int or row["tick"] != tick
                or type(row["grounded"]) is not bool or type(row["jump_pressed"]) is not bool
                or row["jump_pressed"] != (tick == press)
                or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ("x", "y"))
                or any(type(row[k]) is not int for k in ("ground_index", "events", "deaths"))
                or row["ground_index"] not in (-1, 0, 1) or row["events"] < 0 or row["events"] & ~139
                or row["deaths"] not in (0, 1)):
            raise ValueError("Invalid state or input record")
        if row["deaths"] and tick != len(rows):
            raise ValueError("Trace continues beyond first death")
        if grounded_seen and not row["grounded"] and departure is None: departure = tick
        grounded_seen |= row["grounded"]
        if row["events"] & 1: jumps.append(tick)
        if row["events"] & 8: wall_kicks.append(tick)
        if row["grounded"] and row["ground_index"] == 1 and not row["deaths"]:
            if not gap - .45 <= row["x"] <= gap + 30.45 or abs(row["y"] - 1) > .03:
                raise ValueError("Target contact disagrees with geometry")
            if landing is None: landing = tick
    if len(rows) < horizon and rows[-1]["deaths"] != 1:
        raise ValueError("Truncated trial is not a failure outcome")
    return {"departure_tick": departure, "landing_tick": landing, "success": landing is not None,
            "jump_ticks": jumps, "wall_kick_ticks": wall_kicks, "deaths": rows[-1]["deaths"]}


def analyze_jump(envelope, trace):
    p = validate_plan(envelope)
    if set(trace) != {"scope", "reference", "trials"} or trace["scope"] != SCOPE:
        raise ValueError("Wrong gap evidence scope")
    if len(trace["reference"]) != 4 or len(trace["trials"]) != len(p["schedule"]):
        raise ValueError("Incomplete trial set")
    departures = {}; controls = []
    for gap, ref in zip(p["gap_widths"], trace["reference"]):
        if set(ref) != {"gap", "departure_tick", "rows"} or ref["gap"] != gap:
            raise ValueError("Reference identity mismatch")
        m = measurements(ref["rows"], gap, -1, p["horizon_ticks"])
        if m["departure_tick"] != ref["departure_tick"] or m["departure_tick"] is None:
            raise ValueError("Reference departure mismatch")
        departures[gap] = m["departure_tick"]
        if m["success"] or m["jump_ticks"]: controls.append(f"no_jump_reference:{gap}")
    seen = {}; outcomes = []
    for spec, trial in zip(p["schedule"], trace["trials"]):
        press = departures[spec["gap"]] + spec["offset_ticks"]
        if (set(trial) != {"id", "press_tick", "coyote_seconds", "buffer_seconds", "rows"}
                or trial["id"] != spec["id"] or trial["press_tick"] != press
                or not math.isclose(trial["coyote_seconds"], 1/240 if spec["arm"] == "narrow" else .11, abs_tol=1e-7)
                or not math.isclose(trial["buffer_seconds"], .13, abs_tol=1e-7)):
            raise ValueError("Trial schedule or intervention mismatch")
        m = measurements(trial["rows"], spec["gap"], press, p["horizon_ticks"])
        key = (spec["gap"], spec["arm"], spec["offset_ticks"])
        if key in seen and seen[key]["trace_sha256"] != digest(trial["rows"]):
            controls.append(f"identity:{spec['id']}")
        seen[key] = dict(m, trace_sha256=digest(trial["rows"]))
        outcomes.append(dict(spec, **m))
    for arm in ("default", "narrow"):
        if not seen[(2, arm, -1)]["success"]: controls.append(f"on_time_easy:{arm}")
    curves = []
    for gap in p["gap_widths"]:
        accepted = {arm: [d for d in range(-1,25) if seen[(gap,arm,d)]["success"]] for arm in ("default", "narrow")}
        curves.append({"gap": gap, "successful_offsets": accepted,
                       "default_only_offsets": sorted(set(accepted["default"]) - set(accepted["narrow"])),
                       "narrow_only_offsets": sorted(set(accepted["narrow"]) - set(accepted["default"]))})
    return {"status": "passed_controls" if not controls else "failed_controls", "scope": SCOPE,
            "plan_sha256": envelope["plan_sha256"], "trace_sha256": digest(trace),
            "trial_count": 416, "unique_conditions": 208, "reference_runs": 4,
            "control_failures": controls, "curves": curves, "outcomes": outcomes,
            "human_preference_measured": False, "rendering_measured": False,
            "generalizes_to_campaign": False, "statistical_inference": "enumerated deterministic conditions; no population estimate"}


def run_jump(envelope, source, output, timeout=60):
    p = validate_plan(envelope)
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if type(timeout) is not int or not 1 <= timeout <= 300: raise ValueError("Invalid timeout")
    if output == source or output.is_relative_to(source): raise ValueError("Output must be outside source")
    if source_manifest(source, "puma-platformer") != p["source"]: raise ValueError("Source drift")
    output.mkdir(parents=True, exist_ok=False); write_json(output/"plan.json", envelope)
    try:
        if not shutil.which("dotnet"): raise RuntimeError(".NET 8 SDK required")
        with tempfile.TemporaryDirectory(prefix="puma-gap-") as temp:
            work = Path(temp)
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "DOTNET_ROOT") if k in os.environ}
            env.update(HOME=str(work), TMPDIR=str(work), DOTNET_CLI_HOME=str(work), DOTNET_NOLOGO="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")
            for name in p["source"]["files"]: shutil.copyfile(source/name, work/Path(name).name)
            shutil.copyfile(RESOURCES/"PumaJumpHost.cs", work/"PumaJumpHost.cs")
            (work/"host.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>disable</ImplicitUsings><Nullable>disable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>')
            (work/"NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            execute(["dotnet", "build", "host.csproj", "-c", "Release", "--nologo", "-v", "quiet"], work, None, timeout, env)
            trace = json.loads(execute(["dotnet", str(work/"bin/Release/net8.0/host.dll")], work, p, timeout, env))
        write_json(output/"trace.json", trace)
        if source_manifest(source, "puma-platformer") != p["source"]: raise ValueError("Source changed during run")
        result = analyze_jump(envelope, trace)
    except (ValueError, RuntimeError, OSError, TimeoutError) as e:
        result = {"status": "error", "scope": SCOPE, "plan_sha256": envelope["plan_sha256"], "error": str(e)}
    write_json(output/"summary.json", result)
    return result


def verify_jump(output):
    output = Path(output)
    saved = json.loads((output/"summary.json").read_text())
    if saved.get("status") not in ("passed_controls", "failed_controls"): raise ValueError("Incomplete experiment")
    result = analyze_jump(json.loads((output/"plan.json").read_text()), json.loads((output/"trace.json").read_text()))
    if result != saved: raise ValueError("Summary does not match raw evidence")
    return result
