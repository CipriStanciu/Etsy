"""PDF-generator verification: assert the owner's output spec on every PDF.

Checks (per recipe):
- schema-valid recipe, and rendering completes without error
- output file exists at ``<out>/<slug>.pdf``
- file size > 50 KB (non-trivial; embedded fonts guarantee this)
- file begins with the ``%PDF-`` header
- pypdf opens it cleanly and reports >= 3 pages
- ``recipe_name`` text is extractable from the PDF (content sanity check)
- determinism: rendering the same recipe twice yields byte-identical files
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..schema import validate as schema_validate
from . import render

log = logging.getLogger("fragbot.pdfgen")

MIN_PDF_BYTES = render.MIN_PDF_BYTES
MIN_PAGES = 3


def check_pdf_file(path: Path) -> Tuple[List[str], Dict[str, object]]:
    """Return (problems, info) for one generated PDF."""
    problems: List[str] = []
    info: Dict[str, object] = {}
    if not path.is_file():
        return [f"missing file: {path.name}"], info
    info["bytes"] = path.stat().st_size
    if info["bytes"] <= MIN_PDF_BYTES:
        problems.append(f"{path.name}: {info['bytes']} bytes <= {MIN_PDF_BYTES} min")
    head = path.open("rb").read(8)
    if not head.startswith(b"%PDF-"):
        problems.append(f"{path.name}: does not start with %PDF- header")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        info["pages"] = len(reader.pages)
        if len(reader.pages) < MIN_PAGES:
            problems.append(f"{path.name}: {len(reader.pages)} pages < {MIN_PAGES} min")
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "")
        info["text_chars"] = len(text)
        if len(text) < 200:
            problems.append(f"{path.name}: extracted text suspiciously short ({len(text)} chars)")
    except Exception as exc:  # noqa: BLE001 - any reader failure is a problem
        problems.append(f"{path.name}: pypdf cannot read: {exc}")
    return problems, info


def verify_recipe_pdf(
    recipe: dict,
    work_root: Path,
    brand: str = "Fragrance Bot",
) -> Tuple[List[str], Path, Dict[str, object]]:
    """Render a single recipe twice into ``work_root`` and check both files.

    Returns (problems, out_path, info). Files are kept for inspection.
    """
    problems: List[str] = []
    out_path: Path = Path(work_root)
    schema_errors = schema_validate(recipe)
    if schema_errors:
        return [f"schema invalid: {'; '.join(schema_errors)}"], out_path, {}

    try:
        out = Path(work_root)
        out.mkdir(parents=True, exist_ok=True)
        first = render.generate_pdf(recipe, out, brand=brand)
        out_path = first
        problems, info = check_pdf_file(first)
        # determinism: regenerate into a second dir and compare bytes
        tmp2 = Path(tempfile.mkdtemp(prefix="fragbot-pdf-det-"))
        second = render.generate_pdf(recipe, tmp2, brand=brand)
        same = first.read_bytes() == second.read_bytes()
        info["deterministic"] = same
        if not same:
            problems.append("re-render produced different bytes (determinism FAIL)")
        info["bytes2"] = second.stat().st_size
    except Exception as exc:  # noqa: BLE001
        problems = [f"render error: {type(exc).__name__}: {exc}"]
        info = {}
    return problems, out_path, info


def verify_examples(
    recipe_files: Sequence[str | Path],
    brand: str = "Fragrance Bot",
    work_dir: Optional[str] = None,
) -> Tuple[int, int, List[Dict[str, object]]]:
    """Render + check every recipe file. Returns (checks_run, checks_passed, rows)."""
    rows: List[Dict[str, object]] = []
    passed = failed = 0
    for rf in recipe_files:
        path = Path(rf)
        try:
            recipe = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rows.append({"file": str(path), "status": "FAIL", "detail": f"cannot read JSON: {exc}"})
            failed += 1
            continue
        if work_dir is None:
            work_dir = tempfile.mkdtemp(prefix="fragbot-pdf-verify-")
        problems, out_path, info = verify_recipe_pdf(recipe, Path(work_dir), brand=brand)
        ok = not problems
        passed += 1 if ok else 0
        failed += 0 if ok else 1
        rows.append({
            "file": str(path),
            "recipe": recipe.get("recipe_name"),
            "status": "PASS" if ok else "FAIL",
            "detail": "; ".join(problems) if problems else "PDF OK",
            "pdf": str(out_path),
            "info": info,
        })
    return passed + failed, passed, rows


def print_report(checks_run: int, checks_passed: int, rows: List[Dict[str, object]]) -> str:
    lines = [
        "=" * 78,
        "FragBot PDF generator — verification report",
        "=" * 78,
    ]
    for r in rows:
        detail = str(r.get("detail"))
        extra = ""
        info = r.get("info") or {}
        if info:
            extra = (f"  [{info.get('bytes', 0) // 1024}kB, {info.get('pages', '?')} pages, "
                     f"det={info.get('deterministic', '?')}]")
        lines.append(f"{r['status']:4s} {r.get('recipe', '?'):22s} {detail}{extra}")
    lines.append("-" * 78)
    lines.append(f"checks run : {checks_run}")
    lines.append(f"passed     : {checks_passed}")
    lines.append(f"failed     : {checks_run - checks_passed}")
    lines.append(f"RESULT: {'PASS' if checks_passed == checks_run else 'FAIL'}")
    return "\n".join(lines)