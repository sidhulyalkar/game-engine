"""Preregistered paired software experiments, with seed-cluster uncertainty."""
from __future__ import annotations

import json
import math
from pathlib import Path
import random
import statistics

from .commands import suite_scenarios
from .repair import load_evidence
from .runner import run, source_manifest
from .scenario import digest, integer, validate


def seal(payload: dict) -> dict:
    return {"plan": payload, "plan_sha256": digest(payload)}


def validate_plan(envelope: dict) -> dict:
    if set(envelope) != {"plan", "plan_sha256"} or digest(envelope["plan"]) != envelope["plan_sha256"]:
        raise ValueError("Plan fingerprint mismatch")
    p = envelope["plan"]
    if set(p) != {"version", "hypothesis", "template", "primary_endpoint", "sources", "blocks", "schedule", "analysis", "evidence_scope"}:
        raise ValueError("Unsupported plan fields")
    if p["version"] != 1 or p["primary_endpoint"] not in {"final_progress", "deaths"}:
        raise ValueError("Unsupported plan version/endpoint")
    if p["template"] not in {"unicorn-stampede", "puma-platformer"}:
        raise ValueError("Unsupported template")
    if p["template"] == "unicorn-stampede" and p["primary_endpoint"] == "deaths":
        raise ValueError("Unicorn does not measure player deaths")
    if not isinstance(p["hypothesis"], str) or not p["hypothesis"].strip():
        raise ValueError("An explicit hypothesis is required")
    if p["evidence_scope"] != "instrumented_controller_experiment_not_human_or_neural":
        raise ValueError("Invalid evidence scope")
    if p["analysis"] != {"contrast": "candidate-minus-baseline", "unit": "seed_mean_across_worlds", "bootstrap_seed": 2027, "bootstrap_draws": 2000}:
        raise ValueError("Unsupported analysis prescription")
    if set(p["sources"]) != {"baseline", "candidate"}:
        raise ValueError("Two named arms required")
    for source in p["sources"].values():
        if digest(source["files"]) != source["sha256"]:
            raise ValueError("Invalid source fingerprint")
    blocks = p["blocks"]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 60:
        raise ValueError("Provide 1–60 blocks")
    ids = []
    combinations = set()
    for b in blocks:
        if set(b) != {"id", "seed", "world", "scenario"}:
            raise ValueError("Invalid block fields")
        s = validate(b["scenario"])
        if s != b["scenario"] or s["template"] != p["template"] or s["seed"] != b["seed"] or s["setup"]["world"] != b["world"]:
            raise ValueError("Block and scenario disagree")
        if b["id"] != digest(s)[:16] or b["id"] in ids or (b["seed"],b["world"]) in combinations:
            raise ValueError("Duplicate or inconsistent block")
        ids.append(b["id"]); combinations.add((b["seed"],b["world"]))
    world_sets = [{w for seed,w in combinations if seed == s} for s in {s for s,w in combinations}]
    if any(w != world_sets[0] for w in world_sets):
        raise ValueError("Each seed must have the same world coverage")
    expected = {(b, arm) for b in ids for arm in ("baseline", "candidate")}
    schedule = p["schedule"]
    if any(not isinstance(x, dict) or set(x) != {"block", "arm"} for x in schedule):
        raise ValueError("Invalid schedule entries")
    if len(schedule) != len(expected) or {(x["block"],x["arm"]) for x in schedule} != expected:
        raise ValueError("Schedule must contain every paired run exactly once")
    return p


def make_plan(template: str, baseline: Path, candidate: Path, hypothesis: str,
              seeds: list[int], ticks: int, endpoint: str = "final_progress") -> dict:
    integer(ticks, 1, 18000, "ticks")
    if not seeds or len(seeds) > 20 or len(seeds) != len(set(seeds)):
        raise ValueError("Provide 1–20 unique controller seeds")
    blocks = []
    for seed in seeds:
        integer(seed, 0, 2147483647, "seed")
        for s in suite_scenarios(template, seed, ticks):
            s = validate(s)
            blocks.append({"id": digest(s)[:16], "seed": seed, "world": s["setup"]["world"], "scenario": s})
    schedule = [{"block":b["id"],"arm":arm} for b in blocks for arm in ("baseline","candidate")]
    random.Random(2027).shuffle(schedule)
    p = {"version":1,"hypothesis":hypothesis,"template":template,"primary_endpoint":endpoint,
         "sources":{arm:source_manifest(path,template) for arm,path in (("baseline",baseline),("candidate",candidate))},
         "blocks":blocks,"schedule":schedule,
         "analysis":{"contrast":"candidate-minus-baseline","unit":"seed_mean_across_worlds","bootstrap_seed":2027,"bootstrap_draws":2000},
         "evidence_scope":"instrumented_controller_experiment_not_human_or_neural"}
    envelope = seal(p); validate_plan(envelope)
    return envelope


def run_plan(envelope: dict, baseline: Path, candidate: Path, output: Path, timeout: int = 60) -> dict:
    p = validate_plan(envelope)
    sources = {"baseline":baseline,"candidate":candidate}
    for arm,path in sources.items():
        if source_manifest(path,p["template"]) != p["sources"][arm]:
            raise ValueError(f"{arm} changed after planning")
        if output.resolve().is_relative_to(path.resolve()):
            raise ValueError("Study output must be outside both sources")
    output.mkdir(parents=True,exist_ok=False)
    (output/"plan.json").write_text(json.dumps(envelope,indent=2)+"\n")
    blocks = {b["id"]:b for b in p["blocks"]}
    rows = []
    for slot in p["schedule"]:
        relative = f"{slot['block']}/{slot['arm']}"
        result = run(sources[slot["arm"]],blocks[slot["block"]]["scenario"],output/relative,timeout)
        rows.append({**slot,"report":relative,"status":result["status"]})
        # A crash still produces a retained record; never substitute a zero score.
        (output/"execution.json").write_text(json.dumps({"plan_sha256":envelope["plan_sha256"],"runs":rows},indent=2)+"\n")
    return summarize(output)


def paired_effect(deltas: list[float]) -> dict:
    if not deltas or any(not math.isfinite(x) for x in deltas):
        raise ValueError("Finite independent-cluster deltas required")
    mean = statistics.mean(deltas)
    interval = None
    if len(deltas) >= 5:
        rng = random.Random(2027)
        boot = sorted(statistics.mean(rng.choices(deltas,k=len(deltas))) for _ in range(2000))
        interval = [boot[49],boot[1949]]
    return {"mean_delta":mean,"seed_clusters":len(deltas),"bootstrap_95_percentile":interval,
            "uncertainty_note":"Exploratory seed-cluster interval; not a human-population confidence interval. Fewer than five seeds: interval withheld."}


def summarize(output: Path) -> dict:
    envelope = json.loads((output/"plan.json").read_text()); p = validate_plan(envelope)
    execution = json.loads((output/"execution.json").read_text())
    expected = {(x["block"],x["arm"]) for x in p["schedule"]}
    runs = execution["runs"]
    if execution["plan_sha256"] != envelope["plan_sha256"] or len(runs) != len(expected) or {(r["block"],r["arm"]) for r in runs} != expected:
        raise ValueError("Incomplete, duplicated, or mismatched study execution")
    blocks = {b["id"]:b for b in p["blocks"]}
    values, errors, adapters = {}, [], set()
    failures = {"baseline": [], "candidate": []}
    for r in runs:
        relative = f"{r['block']}/{r['arm']}"
        if r["report"] != relative: raise ValueError("Unexpected evidence path")
        folder = output/relative
        if not folder.resolve().is_relative_to(output.resolve()): raise ValueError("External evidence path")
        raw = json.loads((folder/"report.json").read_text())
        if raw.get("status") == "error":
            errors.append({"block":r["block"],"arm":r["arm"],"error":raw.get("error")}); continue
        report = load_evidence(folder)
        if report["source"] != p["sources"][r["arm"]] or report["scenario"] != blocks[r["block"]]["scenario"]:
            raise ValueError("Evidence is not from the planned source/scenario")
        adapters.add(report["adapter_sha256"])
        failures[r["arm"]].extend({"block": r["block"], "code": f["code"]}
                                  for f in report["findings"] if f["severity"] == "failure")
        values[(r["block"],r["arm"])] = report["final"]["progress" if p["primary_endpoint"] == "final_progress" else "deaths"]
    if len(adapters)>1: raise ValueError("Adapters changed within study")
    result = {"version":1,"plan_sha256":envelope["plan_sha256"],"hypothesis":p["hypothesis"],
              "primary_endpoint":p["primary_endpoint"],"scope":p["evidence_scope"],"errors":errors,
              "status":"incomplete" if errors else "complete","optimal_design_established":False,
              "contract_failures": failures, "promotion_decision": "human_review_required"}
    if not errors:
        paired = [{"block":b["id"],"seed":b["seed"],"world":b["world"],
                   "delta":values[(b["id"],"candidate")]-values[(b["id"],"baseline")]} for b in p["blocks"]]
        seeds = sorted({b["seed"] for b in p["blocks"]})
        result.update(pairs=paired, effect=paired_effect([statistics.mean(b["delta"] for b in paired if b["seed"]==s) for s in seeds]))
        result["interpretation"] = "Paired controller response to these source variants only; no automatic winner or causal claim about human enjoyment. Reusing a plan after inspecting results is exploratory."
    (output/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    return result
