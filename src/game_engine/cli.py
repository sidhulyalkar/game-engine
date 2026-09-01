from __future__ import annotations

import argparse
import json
from pathlib import Path

from .orchestrator import Studio
from .config import build_clients, load_provider_specs
from .swarm import SwarmStudio
from .packaging import package_game
from .schema import Brief


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
