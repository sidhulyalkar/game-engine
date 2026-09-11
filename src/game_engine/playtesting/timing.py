"""Positive controls for timing sensitivity, not player or level simulations."""
from __future__ import annotations

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

SCOPE = "imposed_contact_motor_calibration"


def implementation_hash():
    return digest({name: hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest()
                   for name in ("PumaTimingHost.cs", "timing.py")})


def schedule():
    rows = [{"id": f"{mechanism}-{arm}-{delay}-{repeat}", "mechanism": mechanism,
             "arm": arm, "delay_ticks": delay, "repeat": repeat}
            for mechanism in ("coyote", "buffer") for arm in ("default", "narrow")
            for delay in range(25) for repeat in range(2)]
    random.Random(2027).shuffle(rows)
    return rows


def make_timing_plan(source):
    plan = {"version": 1, "scope": SCOPE, "tick_hz": 120,
            "hypothesis": "Shortening one grace window to half a tick reduces delayed jump acceptance while retaining on-time acceptance.",
            "source": source_manifest(Path(source), "puma-platformer"),
            "implementation_sha256": implementation_hash(), "schedule": schedule(),
            "expected_last_accepted_tick": {"coyote": {"default": 13, "narrow": 0},
                                             "buffer": {"default": 15, "narrow": 0}}}
    return {"plan": plan, "plan_sha256": digest(plan)}


def validate_timing_plan(envelope):
    if set(envelope) != {"plan", "plan_sha256"} or digest(envelope["plan"]) != envelope["plan_sha256"]:
        raise ValueError("Timing plan fingerprint mismatch")
    plan = envelope["plan"]
    required = {"version", "scope", "tick_hz", "hypothesis", "source", "implementation_sha256",
                "schedule", "expected_last_accepted_tick"}
    if (set(plan) != required or plan["version"] != 1 or plan["scope"] != SCOPE
            or type(plan["tick_hz"]) is not int or plan["tick_hz"] != 120
            or plan["schedule"] != schedule()
            or plan["implementation_sha256"] != implementation_hash()
            or plan["expected_last_accepted_tick"] != {"coyote": {"default": 13, "narrow": 0}, "buffer": {"default": 15, "narrow": 0}}):
        raise ValueError("Unsupported or changed timing protocol")
    manifest = plan["source"]
    if set(manifest) != {"files", "sha256"} or digest(manifest["files"]) != manifest["sha256"]:
        raise ValueError("Source manifest fingerprint mismatch")
    return plan


def input_steps(trial):
    delay = trial["delay_ticks"]
    if delay == 0:
        return [(True, True)]
    if trial["mechanism"] == "coyote":
        return [(True, False)] + [(False, i == delay) for i in range(1, delay + 1)]
    return [(False, True)] + [(i == delay, False) for i in range(1, delay + 1)]


def analyze_timing(envelope, trace):
    plan = validate_timing_plan(envelope)
    if set(trace) != {"scope", "trials"} or trace["scope"] != SCOPE or len(trace["trials"]) != len(plan["schedule"]):
        raise ValueError("Incomplete or wrong-scope timing trace")
    observed = {}
    mismatches = []
    for spec, trial in zip(plan["schedule"], trace["trials"]):
        if set(trial) != {"id", "coyote_seconds", "buffer_seconds", "steps"} or trial["id"] != spec["id"]:
            raise ValueError("Trial identity/order mismatch")
        for mechanism, standard in (("coyote", .11), ("buffer", .13)):
            expected = 1 / 240 if spec["arm"] == "narrow" and spec["mechanism"] == mechanism else standard
            value = trial[mechanism + "_seconds"]
            if type(value) not in (int, float) or not math.isclose(value, expected, rel_tol=0, abs_tol=1e-7):
                raise ValueError("Unexpected tuning; intervention is not isolated")
        inputs = input_steps(spec)
        if len(trial["steps"]) != len(inputs):
            raise ValueError("Missing motor steps")
        jumps = []
        for i, (step, (grounded, pressed)) in enumerate(zip(trial["steps"], inputs)):
            if (set(step) != {"grounded_before", "jump_pressed", "events", "velocity_y"}
                    or type(step["grounded_before"]) is not bool or step["grounded_before"] != grounded
                    or type(step["jump_pressed"]) is not bool or step["jump_pressed"] != pressed
                    or type(step["events"]) is not int or step["events"] not in (0, 1)
                    or type(step["velocity_y"]) not in (int, float) or not math.isfinite(step["velocity_y"])):
                raise ValueError("Malformed motor measurement or input schedule")
            if step["events"] & 1:
                jumps.append(i)
        accepted = jumps == [len(inputs) - 1]
        boundary = plan["expected_last_accepted_tick"][spec["mechanism"]][spec["arm"]]
        expected = spec["delay_ticks"] <= boundary
        if bool(jumps) != accepted or accepted != expected:
            mismatches.append({"id": spec["id"], "expected_accepted": expected, "jump_steps": jumps})
        key = (spec["mechanism"], spec["arm"], spec["delay_ticks"])
        if key in observed and observed[key]["steps"] != trial["steps"]:
            mismatches.append({"id": spec["id"], "reason": "identity_repeat_mismatch"})
        observed[key] = {"accepted": accepted, "steps": trial["steps"]}
    curves = []
    for mechanism in ("coyote", "buffer"):
        for arm in ("default", "narrow"):
            ticks = [d for d in range(25) if observed[(mechanism, arm, d)]["accepted"]]
            curves.append({"mechanism": mechanism, "arm": arm, "accepted_delay_ticks": ticks,
                           "last_accepted_ms": max(ticks) / 120 * 1000 if ticks else None})
    return {"status": "passed" if not mismatches else "failed", "scope": SCOPE,
            "plan_sha256": envelope["plan_sha256"], "trace_sha256": digest(trace),
            "trial_count": 200, "unique_conditions": 100, "identity_repeats": 2,
            "curves": curves, "mismatches": mismatches, "human_preference_measured": False,
            "level_physics_measured": False, "neural_targets_measured": False}


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_timing(envelope, source, output, timeout=60):
    plan = validate_timing_plan(envelope)
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError("timeout must be 1–300 seconds")
    if output == source or output.is_relative_to(source):
        raise ValueError("Evidence must be outside the source tree")
    if source_manifest(source, "puma-platformer") != plan["source"]:
        raise ValueError("Source changed after planning")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "plan.json", envelope)
    try:
        if not shutil.which("dotnet"):
            raise RuntimeError(".NET 8 SDK is required for real Puma motor calibration")
        with tempfile.TemporaryDirectory(prefix="puma-timing-") as temp:
            work = Path(temp)
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "DOTNET_ROOT") if k in os.environ}
            env.update(HOME=str(work), TMPDIR=str(work), DOTNET_CLI_HOME=str(work),
                       DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
            for name in plan["source"]["files"]:
                shutil.copyfile(source / name, work / Path(name).name)
            shutil.copyfile(RESOURCES / "PumaTimingHost.cs", work / "PumaTimingHost.cs")
            (work / "host.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>disable</ImplicitUsings><Nullable>disable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>')
            (work / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            execute(["dotnet", "build", "host.csproj", "-c", "Release", "--nologo", "-v", "quiet"], work, None, timeout, env)
            trace = json.loads(execute(["dotnet", str(work / "bin/Release/net8.0/host.dll")], work, plan, timeout, env))
        write_json(output / "trace.json", trace)
        if source_manifest(source, "puma-platformer") != plan["source"]:
            raise ValueError("Source changed during calibration")
        result = analyze_timing(envelope, trace)
    except (ValueError, OSError, RuntimeError, TimeoutError) as error:
        result = {"status": "error", "scope": SCOPE, "plan_sha256": envelope["plan_sha256"],
                  "error": f"{type(error).__name__}: {error}"}
    write_json(output / "summary.json", result)
    return result


def verify_timing(output):
    output = Path(output)
    saved = json.loads((output / "summary.json").read_text())
    if saved.get("status") not in ("passed", "failed"):
        raise ValueError("Timing calibration did not complete")
    result = analyze_timing(json.loads((output / "plan.json").read_text()),
                            json.loads((output / "trace.json").read_text()))
    if saved != result:
        raise ValueError("Saved timing summary differs from measured trace")
    return result
