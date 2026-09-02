from __future__ import annotations

import argparse
import json
from pathlib import Path

from .portfolio_selection import write_concept_portfolio
from .schema import Brief


def _source_map(values: list[str]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"source must be NAME=LEADERBOARD_PATH, got {value!r}")
        name, path = value.split("=", 1)
        name = name.strip()
        path = path.strip()
        if not name or not path:
            raise ValueError(f"source must contain a non-empty name and path: {value!r}")
        sources[name] = Path(path)
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m game_engine.portfolio_cli",
        description="Select a mechanically diverse preprototype portfolio from swarm leaderboards.",
    )
    parser.add_argument("brief")
    parser.add_argument("--source", action="append", required=True, help="NAME=leaderboard.json; repeat per swarm")
    parser.add_argument("--out", default="runs/portfolio-latest")
    parser.add_argument("--size", type=int, default=4)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--min-distance", type=float, default=0.28)
    parser.add_argument("--diversity-weight", type=float, default=0.45)
    args = parser.parse_args()

    brief = Brief.from_dict(json.loads(Path(args.brief).read_text()))
    result = write_concept_portfolio(
        brief,
        _source_map(args.source),
        Path(args.out),
        portfolio_size=args.size,
        top_k_per_source=args.top,
        min_distance=args.min_distance,
        diversity_weight=args.diversity_weight,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["portfolio_size_selected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
