"""CLI for the Fragrance Bot promo engine.

    python3 -m fragbot.promo generate <recipe.json|dir> --out <dir> [--brand X]
    python3 -m fragbot.promo verify [--recipes a.json ...] [--out dir]

Generates the four social assets (pin.jpg, story.jpg, tiktok.txt, email.txt)
per recipe. Mirrors the imagesgen/pdfgen CLI conventions.
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
from .render import generate_all
from .verify import print_report, verify_examples

log = logging.getLogger("fragbot.promo")


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
        results = generate_all(recipe, out, brand=args.brand, quality=args.quality)
        print(f"{rf}:")
        for kind in ("pin", "story", "tiktok", "email"):
            print(f"  {kind + ('.jpg' if kind in ('pin', 'story') else '.txt'):<11s} {results[kind]}")
    elapsed = time.time() - t0
    print(f"generated {len(files)} promo set(s) in {elapsed:.1f}s "
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
        files, brand=args.brand, quality=args.quality, work_dir=args.out
    )
    print(print_report(checks_run, checks_passed, rows))
    print(f"(verify took {time.time() - t0:.1f}s)")
    return 0 if checks_passed == checks_run else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m fragbot.promo",
        description="Generate the four social promo assets (Pinterest pin, "
                    "Instagram story, TikTok script, email teaser) for one or "
                    "more Fragrance Bot recipes.",
    )
    parser.add_argument("--brand", default=os.environ.get("FRAGBOT_BRAND", "Fragrance Bot"),
                        help="brand/shop name for watermarks (env FRAGBOT_BRAND)"
                             " [default: Fragrance Bot]")
    parser.add_argument("--quality", type=int, default=90,
                        help="JPEG quality 88-92 (owner spec) [default: 90]")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate pin.jpg/story.jpg/tiktok.txt/email.txt")
    g.add_argument("inputs", nargs="+", help="recipe JSON file(s) or a directory of them")
    g.add_argument("--out", required=True,
                   help="output directory (per-recipe subdir when multiple)")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("verify", help="generate + assert the output spec for example recipes")
    v.add_argument("--recipes", nargs="+",
                   help="recipe JSON files/dirs to verify [default: repo examples/]")
    v.add_argument("--out", default=None,
                   help="work directory for generated sets (kept for inspection) [default: temp]")
    v.add_argument("--no-stress", action="store_false", dest="stress",
                   help="skip the worst-case long-name stress recipe")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())