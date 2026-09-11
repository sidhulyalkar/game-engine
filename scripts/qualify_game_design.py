"""Reproduce the frozen Bolt-speed pilot and export one target-free recording."""
import argparse
import json
from pathlib import Path

from game_engine.playtesting.experiments import run_plan
from game_engine.playtesting.features import export_features
from game_engine.playtesting.runner import source_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unicorn", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    candidate = args.out/"candidate"
    for name in source_manifest(args.unicorn, "unicorn-stampede")["files"]:
        target = candidate/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((args.unicorn/name).read_bytes())
    target = candidate/"src/core.js"
    text = target.read_text()
    old, new = "pers=[{sp:1.14,w:.45,p:1}", "pers=[{sp:1.00,w:.45,p:1}"
    if text.count(old) != 1:
        raise ValueError("The pinned intervention no longer matches uniquely")
    target.write_text(text.replace(old, new, 1))
    plan = json.loads((Path(__file__).parents[1]/"examples/studies/bolt-speed-plan.json").read_text())
    summary = run_plan(plan, args.unicorn, candidate, args.out/"study")
    if summary["status"] != "complete":
        raise RuntimeError("Pilot execution incomplete")
    block = plan["plan"]["blocks"][0]["id"]
    features = export_features(args.out/"study"/block/"baseline", "unicorn-v037-lineage")
    (args.out/"features.json").write_text(json.dumps(features, separators=(",", ":"))+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
