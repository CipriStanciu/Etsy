"""Fragrance Bot recipe-card PDF generator.

Renders the digital-download product — a branded, printable US Letter PDF
recipe card (cover, scent profile, ingredients & equipment, step-by-step
instructions, safety notes) from a recipe JSON produced by the recipe engine.

ReportLab only (BSD licence — free), no network at render time, all fonts are
the same vendored free TTFs the image generator ships. Deterministic:
identical recipe JSON + brand => byte-identical PDF.

    from fragbot.pdfgen import generate_pdf
    path = generate_pdf(recipe, "out/", brand="Fragrance Bot")

CLI:  python -m fragbot.pdfgen --help
"""

from __future__ import annotations

__version__ = "0.1.0"

from .render import generate_pdf, pdf_byte_digest

__all__ = ["generate_pdf", "pdf_byte_digest", "__version__"]