"""CLI for the Fragrance Bot listing image generator.

    python -m fragbot.imagesgen generate <recipe.json|dir> --out <dir>
    python -m fragbot.imagesgen verify [--recipes a.json b.json ...] [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from ..schema import validate
from .render import render_recipe
from .verify import print_report, verify_examples

log = logging.getLogger("fragbot.imagesgen")


def _load_recipe(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        recipe = json.load(fh)
    problems = validate(recipe)
    if problems:
        raise ValueError(f"{path}: schema invalid: {'; '.join(problems)}")
    return recipe


def _collect_recipe_files(arg: str):
    p = Path(arg)
    if p.is_dir():
        return sorted(p.glob("*.json"))
    return [p]


def cmd_generate(args: argparse.Namespace) -> int:
    files: list = []
    for arg in args.inputs:
        files.extend(_collect_recipe_files(arg))
    if not files:
        print("no recipe JSON files found", file=sys.stderr)
        return 2

    t0 = time.time()
    for rf in files:
        recipe = _load_recipe(str(rf))
        out = args.out
        if len(files) > 1:
            out = str(Path(args.out) / recipe["slug"])
        results = render_recipe(recipe, out, brand=args.brand, quality=args.quality)
        print(f"{rf}:")
        for kind, path in results.items():
            print(f"  {kind + '.jpg':<16s} {path}")
    elapsed = time.time() - t0
    print(f"rendered {len(files)} recipe set(s) in {elapsed:.1f}s "
          f"({elapsed / max(1, len(files)):.1f}s per set)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    files: list = []
    for arg in (args.recipes or [str(Path(__file__).resolve().parent.parent.parent / "examples")]):
        files.extend(_collect_recipe_files(arg))
    if not files:
        print("no recipe JSON files found for verify", file=sys.stderr)
        return 2
    t0 = time.time()
    checks_run, checks_passed, rows = verify_examples(
        files, brand=args.brand, quality=args.quality, work_dir=args.out
    )
    report = print_report(checks_run, checks_passed, rows)
    print(report)
    print(f"(verify took {time.time() - t0:.1f}s)")
    return 0 if checks_passed == checks_run else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fragbot.imagesgen",
        description="Render the five Etsy listing images for one or more Fragrance Bot recipes.",
    )
    parser.add_argument("--brand", default=os.environ.get("FRAGBOT_BRAND", "Fragrance Bot"),
                        help="brand/shop name for watermarks (env FRAGBOT_BRAND)"
                             " [default: Fragrance Bot]")
    parser.add_argument("--quality", type=int, default=90,
                        help="JPEG quality 88-92 (owner spec) [default: 90]")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="render 5 JPEGs per recipe JSON")
    g.add_argument("inputs", nargs="+", help="recipe JSON file(s) or a directory of them")
    g.add_argument("--out", required=True, help="output directory (per-recipe subdir when multiple)")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("verify", help="render + assert the output spec for example recipes")
    v.add_argument("--recipes", nargs="+",
                   help="recipe JSON files/dirs to verify [default: repo examples/]")
    v.add_argument("--out", default=None,
                   help="work directory for rendered sets (kept for inspection) [default: temp]")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())