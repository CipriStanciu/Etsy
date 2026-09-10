#!/usr/bin/env python3
"""Fragrance Bot — recipe-card PDF generator verification.

Renders every example recipe and asserts the owner's output spec on each PDF:

  - rendering completes without errors (schema-valid recipe in)
  - output exists as <slug>.pdf
  - file size > 50 KB (non-trivial; extracted text present)
  - file begins with the %PDF- header
  - pypdf opens it cleanly and reports >= 3 pages
  - determinism: two renders of the same recipe are byte-identical

Usage:
    python3 verify_pdfs.py                 # verify repo examples/ (into temp dirs)
    python3 verify_pdfs.py path/*.json     # verify specific recipes
    python3 verify_pdfs.py --out dir       # keep the generated PDFs for inspection
    python3 verify_pdfs.py --brand "My Shop"

Exit code 0 = PASS, 1 = FAIL (mirrors verify.py / verify_images.py conventions).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fragbot.pdfgen.verify import print_report, verify_examples  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recipes", nargs="*", help="recipe JSON files/dirs (default: examples/)")
    ap.add_argument("--out", default=None, help="work dir for the PDFs (default: temp)")
    ap.add_argument("--brand", default="Fragrance Bot", help="brand on cover + footers")
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
        files, brand=args.brand, work_dir=args.out
    )
    print(print_report(checks_run, checks_passed, rows))
    return 0 if checks_passed == checks_run else 1


if __name__ == "__main__":
    sys.exit(main())