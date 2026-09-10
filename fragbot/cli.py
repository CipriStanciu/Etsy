"""Command-line interface for the Fragrance Bot recipe engine.

Examples
--------
    python -m fragbot generate --date 2026-01-26
    python -m fragbot generate --date 2026-01-26 --out recipe.json
    python -m fragbot generate --batch 30 --start 2026-04-01 --outdir batch_out
    python -m fragbot generate --batch 7 --repeat 2 --start 2026-04-01 --outdir seed_library

``--repeat`` writes N recipe variants for each date (batch sequence number 0..N-1),
which is the seeding path for building a starter library faster than one/day.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .generator import batch_generate, generate_recipe


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"error: invalid date {text!r} (expected YYYY-MM-DD)")


def _dump(recipe: dict) -> None:
    print(json.dumps(recipe, indent=2, ensure_ascii=False))


def _write(recipe: dict, path: Path) -> None:
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fragbot",
        description="Fragrance Bot recipe engine — one unique DIY fragrance recipe per day.",
    )
    parser.add_argument("--version", action="version", version=f"fragbot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate one recipe (or a batch of recipes)")
    gen.add_argument("--date", help="recipe date YYYY-MM-DD (default: today)")
    gen.add_argument("--batch", type=int, metavar="N", help="generate N consecutive recipes")
    gen.add_argument("--start", help="first date for a batch (default: --date or today)")
    gen.add_argument("--repeat", type=int, default=1, metavar="R",
                     help="variants per date via batch sequence number (default 1)")
    gen.add_argument("--out", help="write the single recipe to this JSON file")
    gen.add_argument("--outdir", help="directory for batch output (default: ./output)")
    gen.set_defaults(func=_cmd_generate)

    args = parser.parse_args(argv)
    return args.func(args)


def _cmd_generate(args) -> int:
    if args.batch:
        from datetime import timedelta

        start = _parse_date(args.start) if args.start else (_parse_date(args.date) if args.date else date.today())
        outdir = Path(args.outdir or "output")
        outdir.mkdir(parents=True, exist_ok=True)
        cur = start
        count = 0
        for _ in range(args.batch):
            for seq in range(args.repeat):
                recipe = generate_recipe(cur, seq=seq)
                suffix = "" if args.repeat == 1 else f"-v{seq}"
                _write(recipe, outdir / f"recipe-{cur.isoformat()}{suffix}.json")
                count += 1
            cur = cur + timedelta(days=1)
        print(f"generated {count} recipes into {outdir}")
        return 0

    d = _parse_date(args.date) if args.date else date.today()
    recipe = generate_recipe(d)
    if args.out:
        _write(recipe, Path(args.out))
    else:
        _dump(recipe)
    return 0


if __name__ == "__main__":
    sys.exit(main())