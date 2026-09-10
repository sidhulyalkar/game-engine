from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

from .analysis import analyze
from .scenario import digest, validate

RESOURCES = Path(__file__).parent
UNICORN_FILES = [f"src/{n}.js" for n in ("core", "herd", "render", "ui", "top10", "polish", "whip", "worlds", "expansion")]


def source_manifest(source: Path, template: str) -> dict:
    source = source.resolve(strict=True)
    names = UNICORN_FILES if template == "unicorn-stampede" else sorted(str(p.relative_to(source)) for p in (source / "Assets/Wildbound/Core").glob("*.cs"))
    if not names:
        raise ValueError("No supported game source files found")
    hashes = {}
    for name in names:
        p = source / name
        if not p.resolve().is_relative_to(source) or not p.is_file():
            raise ValueError(f"Missing or external source: {name}")
        hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"files": hashes, "sha256": digest(hashes)}


def execute(command: list[str], cwd: Path, payload: dict | None, timeout: int, env: dict) -> str:
    # Minimal environment: never forward model/provider credentials to game code.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   env=env, start_new_session=os.name != "nt")
        try:
            process.communicate(None if payload is None else json.dumps(payload).encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt": process.kill()
            else: os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise TimeoutError(f"Adapter exceeded {timeout}s") from None
        stderr.seek(0)
        errors = stderr.read(8000).decode(errors="replace")
        if process.returncode:
            raise RuntimeError(f"Adapter exited {process.returncode}: {errors}")
        if stdout.tell() > 32_000_000:
            raise ValueError("Adapter output exceeds 32MB")
        stdout.seek(0)
        return stdout.read().decode()


def run(source: Path, scenario: dict, output: Path, timeout: int = 60) -> dict:
    scenario = validate(scenario)
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError("timeout must be 1–300 seconds")
    source = source.resolve(strict=True)
    output = output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Evidence must be outside the game source tree")
    manifest = source_manifest(source, scenario["template"])
    output.mkdir(parents=True, exist_ok=False)
    adapter_names = ["unicorn.mjs"] if scenario["template"] == "unicorn-stampede" else ["PumaHost.cs"]
    adapter_hash = digest({n: hashlib.sha256((RESOURCES/n).read_bytes()).hexdigest() for n in adapter_names})
    report = {"version": 1, "scenario": scenario, "scenario_sha256": digest(scenario),
              "source": manifest, "adapter_sha256": adapter_hash, "status": "error"}
    (output/"scenario.json").write_text(json.dumps(scenario, indent=2)+"\n")
    try:
        with tempfile.TemporaryDirectory(prefix="game-playtest-") as temp:
            work = Path(temp)
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "DOTNET_ROOT") if k in os.environ}
            env.update(HOME=str(work), TMPDIR=str(work), DOTNET_CLI_HOME=str(work),
                       DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
            if scenario["template"] == "unicorn-stampede":
                if not shutil.which("node"): raise RuntimeError("Node.js is required")
                text = execute(["node", str(RESOURCES/"unicorn.mjs"), str(source)], work, scenario, timeout, env)
            else:
                if not shutil.which("dotnet"): raise RuntimeError(".NET 8 SDK is required for the Puma core adapter; Unity rendering is a separate gate")
                # Copy only exact hashed C# sources, never the game's build scripts.
                for name in manifest["files"]:
                    shutil.copyfile(source/name, work/Path(name).name)
                shutil.copyfile(RESOURCES/"PumaHost.cs", work/"PumaHost.cs")
                (work/"host.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>disable</ImplicitUsings><Nullable>disable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>')
                (work/"NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
                execute(["dotnet", "build", "host.csproj", "-c", "Release", "--nologo", "-v", "quiet"], work, None, timeout, env)
                text = execute(["dotnet", str(work/"bin/Release/net8.0/host.dll")], work, scenario, timeout, env)
            trace = json.loads(text)
            if source_manifest(source, scenario["template"]) != manifest:
                raise ValueError("Game source changed during execution")
            report.update(analyze(trace, scenario))
            report.update(trace_sha256=digest(trace), evidence_kind=trace["evidence_kind"], adapter=trace["adapter"])
            (output/"trace.json").write_text(json.dumps(trace, separators=(",", ":"), allow_nan=False)+"\n")
    except (ValueError, OSError, RuntimeError, TimeoutError) as error:
        report.update(status="error", error=f"{type(error).__name__}: {error}")
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    return report


def replay(source: Path, previous: Path, output: Path, timeout: int = 60) -> dict:
    old = json.loads((previous/"report.json").read_text())
    if old.get("status") not in {"passed_checks", "failed"}:
        raise ValueError("Only completed runs can be replayed")
    if digest(json.loads((previous/"trace.json").read_text())) != old["trace_sha256"]:
        raise ValueError("Saved trace does not match its report")
    if source_manifest(source, old["scenario"]["template"]) != old["source"]:
        raise ValueError("Replay requires identical source; use compare for revisions")
    result = run(source, old["scenario"], output, timeout)
    matched = result.get("trace_sha256") == old["trace_sha256"] and result.get("adapter_sha256") == old["adapter_sha256"]
    result["replay_matches"] = matched
    if not matched: result["status"] = "replay_mismatch"
    (output/"report.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def compare(before: dict, after: dict) -> dict:
    if before.get("status") not in {"passed_checks", "failed"} or after.get("status") not in {"passed_checks", "failed"}:
        raise ValueError("Cannot compare incomplete or errored runs")
    if before["scenario_sha256"] != after["scenario_sha256"] or before["adapter_sha256"] != after["adapter_sha256"]:
        raise ValueError("Comparison requires the same scenario and adapter")
    failures = lambda r: {f["code"] for f in r["findings"] if f["severity"] == "failure"}
    old, new = failures(before), failures(after)
    return {"resolved": sorted(old-new), "introduced": sorted(new-old),
            "progress_delta": after["final"]["progress"]-before["final"]["progress"],
            "deaths_delta": (after["final"]["deaths"]-before["final"]["deaths"]
                             if after["final"]["deaths"] is not None and before["final"]["deaths"] is not None else None),
            "decision": "regression" if new-old else "review_required",
            "release_qualified": False, "human_preference_measured": False}
