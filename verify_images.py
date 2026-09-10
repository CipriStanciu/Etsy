#!/usr/bin/env python3
"""Fragrance Bot — listing image generator verification.

Renders all example recipes and asserts the owner's output spec on every set:

  - 5 files, exact names: hero.jpg, ingredients.jpg, pyramid.jpg,
    included.jpg, lifestyle.jpg
  - each 2000x2000 px, RGB, JPEG
  - 300 DPI metadata, sRGB (ICC embedded when available, skipped cleanly)
  - quality 88-92, file size < 10 MB
  - no render errors for any example recipe

Usage:
    python3 verify_images.py                 # verify repo examples/
    python3 verify_images.py path/*.json     # verify specific recipes
    python3 verify_images.py --out dir       # keep rendered sets for inspection
    python3 verify_images.py --brand "My Shop"

Exit code 0 = PASS, 1 = FAIL (mirrors the engine's verify.py convention).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fragbot.imagesgen.verify import print_report, verify_examples  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recipes", nargs="*", help="recipe JSON files/dirs (default: examples/)")
    ap.add_argument("--out", default=None, help="work dir for rendered sets (default: temp)")
    ap.add_argument("--brand", default="Fragrance Bot", help="watermark brand name")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality 88-92")
    args = ap.parse_args()

    files: list = []
    for r in (args.recipes or [str(REPO / "examples")]):
        p = Path(r)
        if p.is_dir():
            files.extend(sorted(p.glob("*.json")))
        else:
            files.append(p)
    if not files:
        print("no recipe JSON files found", file=sys.stderr)
        return 2

    checks_run, checks_passed, rows = verify_examples(
        files, brand=args.brand, quality=args.quality, work_dir=args.out
    )
    print(print_report(checks_run, checks_passed, rows))
    return 0 if checks_passed == checks_run else 1


if __name__ == "__main__":
    sys.exit(main())