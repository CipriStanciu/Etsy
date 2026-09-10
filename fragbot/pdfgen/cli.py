"""CLI for the Fragrance Bot recipe-card PDF generator.

    python -m fragbot.pdfgen generate <recipe.json|dir> --out <dir>
    python -m fragbot.pdfgen verify [--recipes a.json b.json ...] [--out <dir>]
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
from .render import generate_pdf
from .verify import print_report, verify_examples

log = logging.getLogger("fragbot.pdfgen")


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
        out_path = generate_pdf(recipe, args.out, brand=args.brand)
        print(f"{rf}:")
        print(f"  pdf           {out_path}")
    elapsed = time.time() - t0
    print(f"rendered {len(files)} PDF(s) in {elapsed:.1f}s "
          f"({elapsed / max(1, len(files)):.1f}s per recipe)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    files: list = []
    for arg in args.recipes:
        files.extend(_collect_recipe_files(arg))
    if not files:
        print("no recipe JSON files found for verify", file=sys.stderr)
        return 2
    t0 = time.time()
    checks_run, checks_passed, rows = verify_examples(
        files, brand=args.brand, work_dir=args.out
    )
    report = print_report(checks_run, checks_passed, rows)
    print(report)
    print(f"(verify took {time.time() - t0:.1f}s)")
    return 0 if checks_passed == checks_run else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fragbot.pdfgen",
        description="Render the branded, printable PDF recipe card for one or more "
                    "Fragrance Bot recipes (US Letter, deterministic, offline).",
    )
    parser.add_argument("--brand", default=os.environ.get("FRAGBOT_BRAND", "Fragrance Bot"),
                        help="brand/shop name on the cover and footers (env FRAGBOT_BRAND)"
                             " [default: Fragrance Bot]")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="render <slug>.pdf per recipe JSON")
    g.add_argument("inputs", nargs="+", help="recipe JSON file(s) or a directory of them")
    g.add_argument("--out", required=True, help="output directory for the PDFs")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("verify", help="render + assert the output spec for recipes")
    v.add_argument("--recipes", nargs="+",
                   help="recipe JSON files/dirs to verify [default: repo examples/]")
    v.add_argument("--out", default=None,
                   help="work directory for the PDFs (kept for inspection) [default: temp]")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())