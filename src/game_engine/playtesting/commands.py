from __future__ import annotations

import json
from pathlib import Path
import random

from .repair import apply_repair, load_evidence, repair_prompt
from .runner import compare, replay, run


def read(path):
    return json.loads(Path(path).read_text())


def emit(value):
    print(json.dumps(value, indent=2))


def cmd_run(args):
    result = run(Path(args.source), read(args.scenario), Path(args.out), args.timeout)
    emit(result)
    return 0 if result["status"] == "passed_checks" else 2


def cmd_replay(args):
    result = replay(Path(args.source), Path(args.previous), Path(args.out), args.timeout)
    emit(result)
    return 0 if result["replay_matches"] else 2


def cmd_compare(args):
    result = compare(load_evidence(Path(args.before)), load_evidence(Path(args.after)))
    emit(result)
    return 2 if result["decision"] == "regression" else 0


def suite_scenarios(template, seed, ticks):
    rng = random.Random(seed)
    for world in range(3):
        actions = []
        remaining = ticks
        while remaining:
            duration = min(remaining, rng.randint(8, 45))
            if template == "unicorn-stampede":
                buttons = [rng.choice(["left", "right", "up", "down"])]
                buttons += [b for b in ("switch", "dash", "whip") if rng.random() < .3]
                action = {"ticks": duration, "buttons": buttons, "pointer": [rng.random(), rng.random()]}
            else:
                buttons = [rng.choice(["left", "right"])]
                buttons += [b for b in ("jump", "pounce", "attack", "roll", "dash", "interact", "up") if rng.random() < .25]
                action = {"ticks": duration, "buttons": buttons}
            actions.append(action); remaining -= duration
        yield {"version": 1, "template": template, "seed": seed, "setup": {"world": world, **({"entry": "campaign"} if template == "unicorn-stampede" else {})}, "actions": actions}


def cmd_suite(args):
    if not 1 <= args.ticks <= 18000: raise ValueError("ticks must be 1–18000")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for i, scenario in enumerate(suite_scenarios(args.template, args.seed, args.ticks)):
        report = run(Path(args.source), scenario, output/f"world-{i}", args.timeout)
        results.append({"world": i, "status": report["status"], "source": report["source"]["sha256"],
                        "report": f"world-{i}/report.json", "findings": report.get("findings", []), "error": report.get("error")})
    summary = {"controller": "seeded input stress; not a human skill model", "runs": results,
               "release_qualified": False}
    (output/"suite.json").write_text(json.dumps(summary, indent=2)+"\n")
    emit(summary)
    return 0 if all(r["status"] == "passed_checks" for r in results) else 2


def cmd_apply(args):
    result = apply_repair(Path(args.source), Path(args.baseline), read(args.proposal), Path(args.out), args.timeout)
    emit(result)
    return 2 if result["decision"] in {"reject", "regression"} else 0


def cmd_propose(args):
    from ..config import build_clients, load_provider_specs
    from ..swarm import _extract_json
    report = load_evidence(Path(args.baseline))
    system, prompt = repair_prompt(Path(args.source), report, args.file)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    (output/"prompt.json").write_text(json.dumps({"system": system, "user": prompt}, indent=2)+"\n")
    if not args.providers:
        emit({"prompt": str(output/"prompt.json"), "provider_called": False})
        return 0
    clients = build_clients(load_provider_specs(Path(args.providers)))
    if not clients: raise ValueError("No enabled providers")
    # One explicitly selected configured provider per invocation bounds spending.
    spec, client = clients[0]
    proposal = _extract_json(client.complete(system, prompt))
    (output/"proposal.json").write_text(json.dumps(proposal, indent=2)+"\n")
    emit({"proposal": str(output/"proposal.json"), "provider": spec.name,
          "validated_or_applied": False, "next": "playtest-apply"})
    return 0


def register(sub):
    p = sub.add_parser("playtest", help="run a bounded scenario against a trusted template checkout")
    p.add_argument("source"); p.add_argument("scenario"); p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=int, default=60); p.set_defaults(func=cmd_run)
    p = sub.add_parser("playtest-replay", help="replay identical inputs and verify normalized trace equality")
    p.add_argument("source"); p.add_argument("previous"); p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=int, default=60); p.set_defaults(func=cmd_replay)
    p = sub.add_parser("playtest-compare", help="compare same-scenario evidence; never automatically promote")
    p.add_argument("before"); p.add_argument("after"); p.set_defaults(func=cmd_compare)
    p = sub.add_parser("playtest-suite", help="seeded input stress across all three template worlds")
    p.add_argument("template", choices=["unicorn-stampede", "puma-platformer"]); p.add_argument("source")
    p.add_argument("--seed", type=int, default=13); p.add_argument("--ticks", type=int, default=1200)
    p.add_argument("--timeout", type=int, default=60); p.add_argument("--out", required=True); p.set_defaults(func=cmd_suite)
    p = sub.add_parser("playtest-propose", help="prepare a repair prompt; optionally call one configured provider")
    p.add_argument("source"); p.add_argument("baseline"); p.add_argument("--file", action="append", required=True)
    p.add_argument("--providers"); p.add_argument("--out", required=True); p.set_defaults(func=cmd_propose)
    p = sub.add_parser("playtest-apply", help="apply bounded edits to a separate candidate and retest")
    p.add_argument("source"); p.add_argument("baseline"); p.add_argument("proposal"); p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=int, default=60); p.set_defaults(func=cmd_apply)
