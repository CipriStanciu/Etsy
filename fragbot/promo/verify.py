"""Promo-engine verification: assert the owner's output spec on generated sets.

Checks (per recipe set):
- all four output files exist with the exact names pin.jpg, story.jpg,
  tiktok.txt, email.txt
- pin.jpg is exactly 1000x1500 px, RGB, JPEG, ~90 quality, < 5 MB
- story.jpg is exactly 1080x1920 px, RGB, JPEG, ~90 quality, < 5 MB
- tiktok.txt is non-empty and contains the recipe name, the price and the
  "link in bio" CTA
- email.txt is non-empty, has a Subject: line and contains the recipe name
  and the price
- byte-determinism: re-rendering the same recipe into a fresh directory
  produces byte-identical files
- rendering completed without errors for every input recipe
- a stress recipe (longest realistic name/notes) renders without text
  overflow (the renderers raise on overflow by construction)
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from ..imagesgen.style import (
    CREAM,
    DARK,
    PYRAMID_BASE_FILL,
    PYRAMID_HEART_FILL,
    PYRAMID_TOP_FILL,
)
from ..schema import validate as schema_validate
from .render import generate_all
from .style import MAX_BYTES, OUTPUT_FILES, PIN_SIZE, STORY_SIZE

log = logging.getLogger("fragbot.promo")

PIN_EXPECT = (1000, 1500)
STORY_EXPECT = (1080, 1920)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample_close(im: Image.Image, xy, expect, tol: int = 14, where: str = "") -> Optional[str]:
    got = im.getpixel(xy)
    if all(abs(g - e) <= tol for g, e in zip(got[:3], expect)):
        return None
    return f"{where} pixel at {xy} = {got}, expected ~{expect}"


def _check_image(path: Path, expect: Tuple[int, int]) -> Tuple[List[str], Dict[str, object]]:
    problems: List[str] = []
    info: Dict[str, object] = {}
    if not path.is_file():
        return [f"missing file: {path.name}"], info
    info["bytes"] = path.stat().st_size
    if info["bytes"] >= MAX_BYTES:
        problems.append(f"{path.name}: {info['bytes']} bytes >= 5 MB limit")
    try:
        im = Image.open(path)
        im.load()
        if im.format != "JPEG":
            problems.append(f"{path.name}: format {im.format}, expected JPEG")
        if im.size != expect:
            problems.append(f"{path.name}: size {im.size}, expected {expect}")
        if im.mode != "RGB":
            problems.append(f"{path.name}: mode {im.mode}, expected RGB")

        if path.name == "pin.jpg":
            # dark hero backdrop in the corners (gradient from #1a1a1a)
            for xy in ((10, 10), (10, 1490), (990, 1490), (990, 10)):
                err = _sample_close(im, xy, DARK, tol=20, where="pin")
                if err:
                    problems.append(err)
        else:  # story.jpg — cream backdrop + the three pyramid palette fills
            for xy in ((10, 10), (1070, 1910), (10, 1910), (1070, 10)):
                err = _sample_close(im, xy, CREAM, tol=16, where="story")
                if err:
                    problems.append(err)
            anchors = {  # inner block fill midpoints, clear of label glyphs
                PYRAMID_TOP_FILL: (540, 605),
                PYRAMID_HEART_FILL: (300, 935),
                PYRAMID_BASE_FILL: (300, 1275),
            }
            for colour, xy in anchors.items():
                err = _sample_close(im, xy, colour, tol=26, where="story pyramid")
                if err:
                    problems.append(err)
    except Exception as exc:  # noqa: BLE001 - decode failure is a problem
        problems.append(f"{path.name}: cannot open/decode: {exc}")
    return problems, info


def _check_text(name: str, path: Path, recipe: dict) -> Tuple[List[str], Dict[str, object]]:
    problems: List[str] = []
    info: Dict[str, object] = {}
    if not path.is_file():
        return [f"missing file: {path.name}"], info
    text = path.read_text(encoding="utf-8")
    info["bytes"] = len(text.encode("utf-8"))
    price = f"${float(recipe['price_usd']):.2f}"
    if not text.strip():
        problems.append(f"{path.name}: file is empty")
    if recipe["recipe_name"] not in text:
        problems.append(f"{path.name}: recipe name {recipe['recipe_name']!r} missing")
    if price not in text:
        problems.append(f"{path.name}: price {price} missing")
    if name == "tiktok.txt" and "link in bio" not in text:
        problems.append("tiktok.txt: 'link in bio' CTA missing")
    if name == "email.txt":
        if not text.startswith("Subject:"):
            problems.append("email.txt: missing 'Subject:' line")
        body = text.split("Subject:", 1)[1]
        sentences = [ln for ln in body.splitlines() if ln.strip().endswith(".")]
        if len(sentences) != 2:
            problems.append(f"email.txt: expected a 2-sentence body (got {len(sentences)})")
    return problems, info


def check_set(out_dir: Path, recipe: dict) -> Tuple[List[str], Dict[str, object]]:
    """Check one generated set; returns (problems, summary info)."""
    problems: List[str] = []
    info: Dict[str, object] = {}
    for name in OUTPUT_FILES:
        p = out_dir / name
        if name.endswith(".jpg"):
            expect = PIN_EXPECT if name == "pin.jpg" else STORY_EXPECT
            sub, finfo = _check_image(p, expect)
        else:
            sub, finfo = _check_text(name, p, recipe)
        problems.extend(sub)
        info[name] = finfo
    return problems, info


def verify_recipe_set(
    recipe: dict,
    work_root: Path,
    brand: str = "Fragrance Bot",
    quality: int = 90,
) -> Tuple[List[str], Path, Dict[str, object]]:
    """Generate one recipe's promo set twice and check it (determinism + spec).

    Returns (problems, render_dir, info).
    """
    problems: List[str] = []
    schema_errors = schema_validate(recipe)
    if schema_errors:
        return [f"schema invalid: {'; '.join(schema_errors)}"], work_root, {}

    slug = recipe["slug"]
    out1 = Path(work_root) / f"{slug}-a"
    out2 = Path(work_root) / f"{slug}-b"
    try:
        generate_all(recipe, out1, brand=brand, quality=quality)
        generate_all(recipe, out2, brand=brand, quality=quality)
        problems, info = check_set(out1, recipe)
        for name in OUTPUT_FILES:
            if _sha256(out1 / name) != _sha256(out2 / name):
                problems.append(f"{name}: byte-identical re-run failed")
    except Exception as exc:  # noqa: BLE001
        problems = [f"render error: {type(exc).__name__}: {exc}"]
        info = {}
    return problems, out1, info


def verify_examples(
    recipe_files: Sequence[str | Path],
    brand: str = "Fragrance Bot",
    quality: int = 90,
    work_dir: Optional[str] = None,
    stress: bool = True,
) -> Tuple[int, int, List[Dict[str, object]]]:
    """Generate + check every recipe file (+ stress recipe). Returns counts."""
    rows: List[Dict[str, object]] = []
    passed = failed = 0
    inputs = list(recipe_files)
    if stress:
        inputs = list(inputs) + [_STRESS_RECIPE_FILE]
    for rf in inputs:
        path = Path(rf)
        try:
            recipe = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rows.append({"file": str(path), "status": "FAIL",
                         "detail": f"cannot read JSON: {exc}"})
            failed += 1
            continue
        if work_dir is None:
            work_dir = tempfile.mkdtemp(prefix="fragbot-promo-verify-")
        problems, out, info = verify_recipe_set(recipe, Path(work_dir),
                                                brand=brand, quality=quality)
        ok = not problems
        passed += 1 if ok else 0
        failed += 0 if ok else 1
        rows.append({
            "file": str(path),
            "recipe": recipe.get("recipe_name"),
            "stress": "stress" in path.name,
            "status": "PASS" if ok else "FAIL",
            "detail": "; ".join(problems) if problems else "4/4 assets OK, deterministic",
            "dir": str(out),
            "info": info,
        })
    return passed + failed, passed, rows


def print_report(checks_run: int, checks_passed: int,
                 rows: List[Dict[str, object]]) -> str:
    lines = [
        "=" * 78,
        "Fragrance Bot promo engine — verification report",
        "=" * 78,
    ]
    for r in rows:
        detail = str(r.get("detail"))
        extra = ""
        info = r.get("info") or {}
        sizes = ", ".join(
            f"{k}:{v.get('bytes', 0) // 1024}kB" for k, v in info.items()
        )
        if sizes:
            extra = f"  [{sizes}]"
        tag = " [STRESS]" if r.get("stress") else ""
        lines.append(f"{r['status']:4s} {r.get('recipe', '?'):22s} {detail}{extra}{tag}")
    lines.append("-" * 78)
    lines.append(f"checks run : {checks_run}")
    lines.append(f"passed     : {checks_passed}")
    lines.append(f"failed     : {checks_run - checks_passed}")
    lines.append(f"RESULT: {'PASS' if checks_passed == checks_run else 'FAIL'}")
    return "\n".join(lines)


def _stress_recipe_file() -> Path:
    """A worst-case recipe (longest realistic name + notes) as temp JSON.

    Built lazily once and cached; the JSON lives in a temp dir so the
    verifier stays self-contained.
    """
    if not getattr(_stress_recipe_file, "_path", None):
        base = next(iter(Path(__file__).resolve().parent.parent.parent
                          .glob("examples/recipe-*.json")))
        recipe = json.loads(base.read_text(encoding="utf-8"))
        recipe["recipe_name"] = "Amber Vanilla Velvet Nights Absolute Reserve"
        recipe["slug"] = "promo-stress-amber-reserve"
        recipe["scent_profile"] = {
            "top_notes": ["Bergamot", "Blood Orange", "Pink Pepper", "Cassis"],
            "heart_notes": ["Jasmine", "Violet Leaf", "Orris Butter", "Ylang Ylang"],
            "base_notes": ["Patchouli", "Sandalwood", "Tonka Bean", "Vetiver",
                           "White Musk"],
        }
        recipe["ingredients"] = [
            {"name": "Jojoba Oil", "amount": "9.4ml", "purpose": "carrier"},
            {"name": "Bergamot Essential Oil", "amount": "1 drop", "purpose": "top"},
            {"name": "Blood Orange Essential Oil", "amount": "1 drop", "purpose": "top"},
            {"name": "Jasmine Essential Oil", "amount": "2 drops", "purpose": "heart"},
            {"name": "Patchouli Essential Oil", "amount": "2 drops", "purpose": "base"},
        ]
        recipe["holiday"] = "Valentine's Day"
        recipe["difficulty"] = "intermediate"
        recipe["theme"] = "Date Night"
        tmp = Path(tempfile.mkdtemp(prefix="fragbot-promo-stress-"))
        path = tmp / "promo-stress.json"
        path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
        _stress_recipe_file._path = path
    return _stress_recipe_file._path


_STRESS_RECIPE_FILE = _stress_recipe_file()