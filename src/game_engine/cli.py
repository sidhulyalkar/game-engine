from __future__ import annotations

import argparse
import json
from pathlib import Path

from .orchestrator import Studio
from .config import build_clients, load_provider_specs
from .swarm import SwarmStudio
from .packaging import package_game
from .prototype import PrototypeForge
from .reality import BrowserRealityLab
from .source_audit import SourceGameplayLab
from .repair import RepairForge
from .repair_cycle import run_repair_cycle
from .schema import Brief, Concept


def cmd_ideate(args: argparse.Namespace) -> int:
    brief = Brief.from_dict(json.loads(Path(args.brief).read_text()))
    manifest = Studio(seed=args.seed).run(brief, Path(args.out), count=args.concepts)
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_swarm_ideate(args: argparse.Namespace) -> int:
    brief = Brief.from_dict(json.loads(Path(args.brief).read_text()))
    specs = load_provider_specs(Path(args.providers))
    clients = build_clients(specs)
    manifest = SwarmStudio(clients, seed=args.seed, max_workers=args.workers).run(
        brief, Path(args.out), deterministic_seeds=args.seeds, concepts_per_call=args.per_call
    )
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_swarm_build(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.winner).read_text())
    brief = Brief.from_dict(payload["brief"])
    concept = Concept.from_dict(payload["concept"])
    specs = load_provider_specs(Path(args.providers))
    clients = build_clients(specs)
    results = PrototypeForge(clients, max_workers=args.workers).build(brief, concept, Path(args.out))
    print(json.dumps([r.__dict__ if hasattr(r, "__dict__") else {k: getattr(r, k) for k in r.__slots__} for r in results], indent=2))
    return 0 if any(r.ok for r in results) else 2


def cmd_reality(args: argparse.Namespace) -> int:
    browsers = [part.strip() for part in args.browsers.split(",") if part.strip()]
    if not browsers:
        raise ValueError("at least one browser is required")
    summary = BrowserRealityLab(
        browsers=browsers,
        timeout_ms=args.timeout_ms,
        viewport_width=args.width,
        viewport_height=args.height,
    ).run(Path(args.builds), Path(args.out))
    print(json.dumps(summary, indent=2))
    return 0 if summary["full_pass_build_ids"] else 2


def cmd_source_audit(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.winner).read_text())
    brief = Brief.from_dict(payload["brief"])
    concept = Concept.from_dict(payload["concept"])
    specs = load_provider_specs(Path(args.providers))
    clients = build_clients(specs)
    summary = SourceGameplayLab(clients, max_workers=args.workers).run(
        brief,
        concept,
        Path(args.builds),
        Path(args.out),
        Path(args.reality) if args.reality else None,
    )
    print(json.dumps(summary, indent=2))
    return 0 if any(row.get("critic_count", 0) >= args.min_critics for row in summary["ranking"]) else 2


def cmd_repair(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.winner).read_text())
    brief = Brief.from_dict(payload["brief"])
    concept = Concept.from_dict(payload["concept"])
    specs = load_provider_specs(Path(args.providers))
    clients = build_clients(specs)
    results = RepairForge(clients, max_workers=args.workers).build(
        brief,
        concept,
        Path(args.builds),
        Path(args.audits),
        Path(args.out),
        max_parents=args.max_parents,
    )
    print(json.dumps([r.__dict__ if hasattr(r, "__dict__") else {k: getattr(r, k) for k in r.__slots__} for r in results], indent=2))
    return 0 if not results or any(r.ok for r in results) else 2


def cmd_repair_cycle(args: argparse.Namespace) -> int:
    browsers = [part.strip() for part in args.browsers.split(",") if part.strip()]
    summary = run_repair_cycle(
        Path(args.winner),
        Path(args.builds),
        Path(args.audits),
        Path(args.repair_providers),
        Path(args.audit_providers),
        Path(args.out),
        browsers=browsers,
        max_parents=args.max_parents,
        workers=args.workers,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] in {"complete", "no_repair_candidates"} else 2


def cmd_pack(args: argparse.Namespace) -> int:
    report = package_game(Path(args.source), Path(args.zip), limit_bytes=args.limit)
    print(f"{report.compressed_bytes}/{report.limit_bytes} bytes ({'PASS' if report.ok else 'FAIL'})")
    for warning in report.warnings:
        print(f"warning: {warning}")
    return 0 if report.ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="game-engine", description="Evolutionary swarm studio for tiny web games")
    sub = parser.add_subparsers(dest="command", required=True)

    ideate = sub.add_parser("ideate", help="generate, mutate, judge, and rank game concepts")
    ideate.add_argument("brief")
    ideate.add_argument("--out", default="runs/latest")
    ideate.add_argument("--seed", type=int, default=13)
    ideate.add_argument("--concepts", type=int, default=24)
    ideate.set_defaults(func=cmd_ideate)

    swarm = sub.add_parser("swarm-ideate", help="run configured LLM providers against specialist studio roles")
    swarm.add_argument("brief")
    swarm.add_argument("--providers", default="studio.example.json")
    swarm.add_argument("--out", default="runs/swarm-latest")
    swarm.add_argument("--seed", type=int, default=13)
    swarm.add_argument("--seeds", type=int, default=16)
    swarm.add_argument("--per-call", type=int, default=3)
    swarm.add_argument("--workers", type=int, default=8)
    swarm.set_defaults(func=cmd_swarm_ideate)

    build = sub.add_parser("swarm-build", help="turn a winning concept into competing runnable model prototypes")
    build.add_argument("winner")
    build.add_argument("--providers", default="studio.example.json")
    build.add_argument("--out", default="runs/build-latest")
    build.add_argument("--workers", type=int, default=4)
    build.set_defaults(func=cmd_swarm_build)

    reality = sub.add_parser("reality-check", help="run byte-qualified prototypes in real browsers and capture evidence")
    reality.add_argument("builds", help="prototype forge output directory containing builds.json")
    reality.add_argument("--out", default="runs/reality-latest")
    reality.add_argument("--browsers", default="chromium,firefox,webkit")
    reality.add_argument("--timeout-ms", type=int, default=10_000)
    reality.add_argument("--width", type=int, default=1280)
    reality.add_argument("--height", type=int, default=720)
    reality.set_defaults(func=cmd_reality)

    audit = sub.add_parser("source-audit", help="have independent gameplay critics inspect source plus browser evidence")
    audit.add_argument("winner", help="champion winner.json defining the intended concept")
    audit.add_argument("builds", help="prototype forge output directory containing builds.json")
    audit.add_argument("--reality", default=None, help="optional Browser Reality Lab output directory")
    audit.add_argument("--providers", default="studio.nvidia.audit.json")
    audit.add_argument("--out", default="runs/audit-latest")
    audit.add_argument("--workers", type=int, default=4)
    audit.add_argument("--min-critics", type=int, default=2)
    audit.set_defaults(func=cmd_source_audit)

    repair = sub.add_parser("repair", help="create surgical child builds from prototypes marked repair by gameplay audits")
    repair.add_argument("winner", help="champion winner.json defining the intended concept")
    repair.add_argument("builds", help="parent prototype directory containing builds.json")
    repair.add_argument("audits", help="source-audit output directory containing audits.json")
    repair.add_argument("--providers", default="studio.nvidia.repair.json")
    repair.add_argument("--out", default="runs/repairs-latest")
    repair.add_argument("--workers", type=int, default=4)
    repair.add_argument("--max-parents", type=int, default=1)
    repair.set_defaults(func=cmd_repair)

    cycle = sub.add_parser("repair-cycle", help="repair one lineage and re-run byte, browser, critic, and parent/child evidence gates")
    cycle.add_argument("winner")
    cycle.add_argument("builds")
    cycle.add_argument("audits")
    cycle.add_argument("--repair-providers", default="studio.nvidia.repair.json")
    cycle.add_argument("--audit-providers", default="studio.nvidia.audit.json")
    cycle.add_argument("--out", default="runs/repair-cycle-latest")
    cycle.add_argument("--browsers", default="chromium,firefox,webkit")
    cycle.add_argument("--timeout-ms", type=int, default=12_000)
    cycle.add_argument("--workers", type=int, default=4)
    cycle.add_argument("--max-parents", type=int, default=1)
    cycle.set_defaults(func=cmd_repair_cycle)

    pack = sub.add_parser("pack", help="zip a game and enforce the compressed byte budget")
    pack.add_argument("source")
    pack.add_argument("--zip", default="dist/game.zip")
    pack.add_argument("--limit", type=int, default=13 * 1024)
    pack.set_defaults(func=cmd_pack)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
