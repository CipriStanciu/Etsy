#!/usr/bin/env python3
"""Fragrance Bot — promo engine verification.

Generates the four social assets for every example recipe (plus a
worst-case long-name stress recipe) and asserts the owner's output spec:

  - pin.jpg   exactly 1000x1500 px, RGB, JPEG (~90 quality), < 5 MB
  - story.jpg exactly 1080x1920 px, RGB, JPEG (~90 quality), < 5 MB
  - tiktok.txt non-empty, contains recipe name + price + "link in bio" CTA
  - email.txt non-empty, Subject: line, 2-sentence body with name + price
  - byte-determinism: re-generating the same recipe is byte-identical
  - no text overflow (renderers raise on overflow by construction; the
    stress recipe exercises the longest realistic name/notes)

Usage:
    python3 verify_promo.py                 # verify repo examples/
    python3 verify_promo.py path/*.json     # verify specific recipes
    python3 verify_promo.py --out dir       # keep generated sets
    python3 verify_promo.py --no-stress     # skip the long-name stress recipe

Exit code 0 = PASS, 1 = FAIL (mirrors verify.py / verify_images.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fragbot.promo.verify import print_report, verify_examples  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recipes", nargs="*", help="recipe JSON files/dirs (default: examples/)")
    ap.add_argument("--out", default=None, help="work dir for generated sets (default: temp)")
    ap.add_argument("--brand", default="Fragrance Bot", help="watermark brand name")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality 88-92")
    ap.add_argument("--no-stress", action="store_false", dest="stress",
                    help="skip the worst-case long-name stress recipe")
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
        files, brand=args.brand, quality=args.quality, work_dir=args.out,
        stress=args.stress,
    )
    print(print_report(checks_run, checks_passed, rows))
    return 0 if checks_passed == checks_run else 1


if __name__ == "__main__":
    sys.exit(main())