"""Image-generator verification: assert the owner's output spec on rendered sets.

Checks (per recipe set):
- all 5 output files exist with the exact names hero.jpg, ingredients.jpg,
  pyramid.jpg, included.jpg, lifestyle.jpg
- every file opens as a JPEG, is exactly 2000x2000 px, RGB mode
- 300 DPI metadata present in the JPEG header
- embedded sRGB ICC profile present *or* skipped cleanly (informational)
- file size < 10 MB
- JPEG quality estimate lands in the 88-92 band (±6 for the encode-size
  heuristic — a coarse but honest sanity check; the save path itself enforces
  the exact 88-92 band and raises otherwise)
- rendering completed without errors for every input recipe
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from . import render
from ..schema import validate as schema_validate

log = logging.getLogger("fragbot.imagesgen")

EXPECTED_FILES = ["hero.jpg", "ingredients.jpg", "pyramid.jpg", "included.jpg", "lifestyle.jpg"]
CANVAS = 2000
MAX_BYTES = 10 * 1024 * 1024  # < 10 MB
QUALITY_BAND = (88, 92)       # owner spec
QUALITY_EST_TOLERANCE = 6     # heuristic slack for the re-encode estimate


def estimate_quality(path: str) -> int:
    """Best-guess JPEG quality by re-encoding size matching (85-100 range)."""
    img = Image.open(path)
    target = os.path.getsize(path)
    best_q, best_d = 90, float("inf")
    for q in range(70, 101, 5):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, subsampling=0)
        d = abs(len(buf.getvalue()) - target)
        if d < best_d:
            best_d, best_q = d, q
    return best_q


def check_image_file(path: Path) -> Tuple[List[str], Dict[str, object]]:
    """Return (problems, info) for a single JPEG."""
    problems: List[str] = []
    info: Dict[str, object] = {}
    if not path.is_file():
        return [f"missing file: {path.name}"], info
    info["bytes"] = os.path.getsize(path)
    if info["bytes"] >= MAX_BYTES:
        problems.append(f"{path.name}: {info['bytes']} bytes >= 10 MB limit")
    try:
        with Image.open(path) as im:
            info["format"] = im.format
            info["size"] = im.size
            info["mode"] = im.mode
            info["dpi"] = im.info.get("dpi")
            info["icc"] = "icc_profile" in im.info
            if im.format != "JPEG":
                problems.append(f"{path.name}: format is {im.format}, expected JPEG")
            if im.size != (CANVAS, CANVAS):
                problems.append(f"{path.name}: size {im.size}, expected {CANVAS}x{CANVAS}")
            if im.mode != "RGB":
                problems.append(f"{path.name}: mode {im.mode}, expected RGB")
            dpi = im.info.get("dpi")
            if dpi is None or not (295 <= dpi[0] <= 305 and 295 <= dpi[1] <= 305):
                problems.append(f"{path.name}: 300 DPI metadata missing/off ({dpi})")
            est = estimate_quality(str(path))
            info["quality_est"] = est
            lo, hi = QUALITY_BAND[0] - QUALITY_EST_TOLERANCE, QUALITY_BAND[1] + QUALITY_EST_TOLERANCE
            if not (lo <= est <= hi):
                problems.append(
                    f"{path.name}: estimated quality {est} outside {QUALITY_BAND} band (±{QUALITY_EST_TOLERANCE})"
                )
    except Exception as exc:  # noqa: BLE001 - any decode failure is a problem
        problems.append(f"{path.name}: cannot open/decode: {exc}")
    return problems, info


def check_recipe_set(out_dir: Path) -> Tuple[List[str], Dict[str, object]]:
    """Check one rendered set; returns (problems, summary info)."""
    problems: List[str] = []
    info: Dict[str, object] = {}
    for name in EXPECTED_FILES:
        p = out_dir / name
        sub, finfo = check_image_file(p)
        problems.extend(sub)
        info[name] = finfo
    return problems, info


def verify_recipe_set(
    recipe: dict,
    work_root: Path,
    brand: str = "Fragrance Bot",
    quality: int = 90,
) -> Tuple[List[str], Path, Dict[str, object]]:
    """Render a single recipe into a fresh subdir of ``work_root`` and check it.

    Returns (problems, render_dir, info). The render dir is populated even on
    failure so it can be inspected.
    """
    problems: List[str] = []
    schema_errors = schema_validate(recipe)
    if schema_errors:
        return [f"schema invalid: {'; '.join(schema_errors)}"], work_root, {}

    out = Path(work_root) / recipe["slug"]
    out.mkdir(parents=True, exist_ok=True)
    try:
        render.render_recipe(recipe, out, brand=brand, quality=quality)
        problems, info = check_recipe_set(out)
    except Exception as exc:  # noqa: BLE001
        problems = [f"render error: {type(exc).__name__}: {exc}"]
        info = {}
    return problems, out, info


def verify_examples(
    recipe_files: Sequence[str | Path],
    brand: str = "Fragrance Bot",
    quality: int = 90,
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
            work_dir = tempfile.mkdtemp(prefix="fragbot-images-verify-")
        problems, out, info = verify_recipe_set(recipe, Path(work_dir), brand=brand, quality=quality)
        ok = not problems
        passed += 1 if ok else 0
        failed += 0 if ok else 1
        rows.append({
            "file": str(path),
            "recipe": recipe.get("recipe_name"),
            "status": "PASS" if ok else "FAIL",
            "detail": "; ".join(problems) if problems else "5/5 images OK",
            "dir": str(out),
            "info": info,
        })
    return passed + failed, passed, rows


def print_report(checks_run: int, checks_passed: int, rows: List[Dict[str, object]]) -> str:
    lines = [
        "=" * 78,
        "FragBot listing image generator — verification report",
        "=" * 78,
    ]
    for r in rows:
        detail = str(r.get("detail"))
        extra = ""
        info = r.get("info") or {}
        sizes = ", ".join(f"{k}:{v.get('bytes', 0) // 1024}kB q~{v.get('quality_est', '?')}"
                          for k, v in info.items())
        if sizes:
            extra = f"  [{sizes}]"
        lines.append(f"{r['status']:4s} {r.get('recipe', '?'):22s} {detail}{extra}")
    lines.append("-" * 78)
    lines.append(f"checks run : {checks_run}")
    lines.append(f"passed     : {checks_passed}")
    lines.append(f"failed     : {checks_run - checks_passed}")
    lines.append(f"RESULT: {'PASS' if checks_passed == checks_run else 'FAIL'}")
    return "\n".join(lines)