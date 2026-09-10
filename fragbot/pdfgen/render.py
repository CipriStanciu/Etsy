"""Recipe-card PDF renderer (ReportLab, US Letter, fully offline).

Builds the digital-download product sold on Etsy: a branded, printable PDF
recipe card per recipe JSON. One file per recipe → ``<slug>.pdf``.

Design
------
- Page size: **US Letter** (8.5 x 11 in, 612 x 792 pt), margins 54 pt (0.75 in).
- Page 1 is a dark cover (#1a1a1a) with gold accents — same design language as
  the listing image hero card — drawn directly on canvas for pixel control.
- Interior pages are cream (#faf7f0) with Playfair Display headings, Lato
  body text and Cormorant Garamond accents, drawn with Platypus flowables so
  every paragraph/table wraps automatically (no overflow possible).
- The recipe's 7-day ``theme`` nudges the accent colour via
  ``fragbot.imagesgen.style.accent_for_theme``, exactly as it does for the
  listing images, so the PDF feels like part of the same product line.
- Deterministic: the canvas is created with ``invariant=1`` (no timestamps /
  document ID), fonts are the same vendored free TTFs as the image generator,
  so identical input JSON → byte-identical PDF.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from reportlab.graphics.shapes import Drawing, Line, Polygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..schema import assert_valid
from ..imagesgen.style import (
    CATEGORY_LABEL,
    CATEGORY_TAGLINE,
    CREAM,
    CREAM_DEEP,
    DARK,
    DARK_RAISED,
    DIFFICULTY_LABEL,
    GOLD,
    GOLD_DARK,
    GOLD_LIGHT,
    GOLD_LINE,
    INK,
    INK_SOFT,
    PURPOSE_META,
    PYRAMID_BASE_EDGE,
    PYRAMID_BASE_FILL,
    PYRAMID_HEART_EDGE,
    PYRAMID_HEART_FILL,
    PYRAMID_TOP_EDGE,
    PYRAMID_TOP_FILL,
    WHITE,
    accent_for_theme,
)
from .fonts import (
    CORMORANT_BOLD,
    CORMORANT_IT,
    CORMORANT_MED,
    CORMORANT_REG,
    CORMORANT_SEMI,
    LATO_BLACK,
    LATO_BOLD,
    LATO_IT,
    LATO_REG,
    PLAYFAIR_BLACK,
    PLAYFAIR_BOLD,
    PLAYFAIR_IT,
    PLAYFAIR_REG,
    register_all,
)

log = logging.getLogger("fragbot.pdfgen")

# --- geometry ---------------------------------------------------------------
PAGE_W, PAGE_H = letter                      # 612 x 792 pt (US Letter)
MARGIN = 54                                  # 0.75 in
CONTENT_W = PAGE_W - 2 * MARGIN              # 504 pt
FRAME_TOP = PAGE_H - 62                      # interior content top
FRAME_BOTTOM = 58                            # interior content bottom
FOOTER_Y = 34                                # footer baseline

COPYRIGHT_YEAR = 2026                        # recipe era of the seed library
MIN_PDF_BYTES = 50 * 1024                    # verification: > 50 KB

BALANCE = (("Top", "30%", PYRAMID_TOP_FILL, PYRAMID_TOP_EDGE),
           ("Heart", "50%", PYRAMID_HEART_FILL, PYRAMID_HEART_EDGE),
           ("Base", "20%", PYRAMID_BASE_FILL, PYRAMID_BASE_EDGE))

# --- colour helpers ---------------------------------------------------------
def _C(rgb) -> colors.Color:
    r, g, b = rgb
    return colors.Color(r / 255.0, g / 255.0, b / 255.0)


DARK_C = _C(DARK)
CREAM_C = _C(CREAM)
CREAM_DEEP_C = _C(CREAM_DEEP)
GOLD_C = _C(GOLD)
GOLD_DARK_C = _C(GOLD_DARK)
GOLD_LIGHT_C = _C(GOLD_LIGHT)
GOLD_LINE_C = _C(GOLD_LINE)
INK_C = _C(INK)
INK_SOFT_C = _C(INK_SOFT)
SAFETY_BG = _C((252, 243, 224))              # pale warm amber panel
WHITE_C = colors.white


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


# --- styles -----------------------------------------------------------------
def _styles() -> dict:
    kicker = ParagraphStyle(
        "kicker", fontName=CORMORANT_BOLD, fontSize=12.5, leading=15,
        textColor=GOLD_DARK_C, spaceAfter=2)
    title = ParagraphStyle(
        "title", fontName=PLAYFAIR_BOLD, fontSize=25, leading=29,
        textColor=INK_C, spaceAfter=4)
    body = ParagraphStyle(
        "body", fontName=LATO_REG, fontSize=10.5, leading=15.5,
        textColor=INK_C, spaceAfter=6)
    note = ParagraphStyle(
        "note", fontName=LATO_REG, fontSize=8.8, leading=12,
        textColor=INK_SOFT_C)
    s = {
        "kicker": kicker,
        "title": title,
        "body": body,
        "body-center": ParagraphStyle(
            "body-center", parent=body, alignment=TA_CENTER),
        "note": note,
        "ing-name": ParagraphStyle(
            "ing-name", fontName=LATO_BOLD, fontSize=10.2, leading=13,
            textColor=INK_C),
        "ing-amount": ParagraphStyle(
            "ing-amount", fontName=LATO_REG, fontSize=10.2, leading=13,
            textColor=INK_C),
        "ing-purpose": ParagraphStyle(
            "ing-purpose", fontName=LATO_BOLD, fontSize=9.3, leading=13,
            textColor=INK_C),
        "eq-item": ParagraphStyle(
            "eq-item", fontName=LATO_REG, fontSize=10.2, leading=14.5,
            textColor=INK_C, leftIndent=4),
        "step": ParagraphStyle(
            "step", fontName=LATO_REG, fontSize=10.6, leading=16,
            textColor=INK_C),
        "safety-item": ParagraphStyle(
            "safety-item", fontName=LATO_REG, fontSize=10.3, leading=15.5,
            textColor=INK_C),
        "stat-label": ParagraphStyle(
            "stat-label", fontName=LATO_BOLD, fontSize=8.4, leading=10.5,
            textColor=GOLD_DARK_C, alignment=TA_CENTER),
        "stat-value": ParagraphStyle(
            "stat-value", fontName=LATO_REG, fontSize=10.6, leading=13.5,
            textColor=INK_C, alignment=TA_CENTER),
        "panel-title": ParagraphStyle(
            "panel-title", fontName=CORMORANT_BOLD, fontSize=13.5, leading=17,
            textColor=GOLD_DARK_C),
    }
    return s


# ---------------------------------------------------------------------------
# Canvas with deterministic output and total-page footers
# ---------------------------------------------------------------------------
class _NumberedCanvas(pdfcanvas.Canvas):
    """Canvas that (a) runs with invariant=1 (byte-deterministic PDFs) and
    (b) draws the brand footer with 'Page X of Y' on every page, knowing the
    final page count (standard ReportLab NumberedCanvas pattern)."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("pageCompression", None)
        kwargs.pop("invariant", None)          # we force invariant=1 ourselves
        super().__init__(*args, invariant=1, pageCompression=1, **kwargs)
        self._fb_states: list = []
        self._fb_brand = "Fragrance Bot"
        self._fb_accent = GOLD

    def showPage(self):
        self._fb_states.append(dict(self.__dict__))
        self._startPage()

    def set_fb_meta(self, brand: str, accent: tuple) -> None:
        self._fb_brand = brand
        self._fb_accent = accent

    def _draw_footer(self, page_no: int, total: int) -> None:
        c = self
        brand = self._fb_brand
        if page_no == 1:
            ink = GOLD_LIGHT_C
            accent = _C(self._fb_accent)
            resale = GOLD_LIGHT_C
        else:
            ink = INK_SOFT_C
            accent = GOLD_DARK_C
            resale = INK_SOFT_C
        c.setStrokeColor(accent)
        c.setLineWidth(0.7)
        c.line(MARGIN, FOOTER_Y + 9, PAGE_W - MARGIN, FOOTER_Y + 9)
        c.setFillColor(ink)
        c.setFont(LATO_REG, 7.6)
        c.drawString(MARGIN, FOOTER_Y, brand)
        c.drawCentredString(PAGE_W / 2, FOOTER_Y, "For personal use. Not for commercial resale.")
        c.setFillColor(resale)
        c.drawRightString(
            PAGE_W - MARGIN, FOOTER_Y,
            f"© {COPYRIGHT_YEAR} {brand}. All rights reserved.   Page {page_no} of {total}",
        )

    def save(self):
        total = len(self._fb_states)
        for i, state in enumerate(self._fb_states, 1):
            self.__dict__.update(state)
            self._draw_footer(i, total)
            super().showPage()
        super().save()


class _DrawingFlowable(Flowable):
    """Wrap a reportlab.graphics Drawing so it flows like a normal flowable."""

    def __init__(self, drawing: Drawing):
        self.drawing = drawing
        self.width = drawing.width
        self.height = drawing.height

    def draw(self):
        self.drawing.drawOn(self.canv, 0, 0)

    def wrap(self, availWidth, availHeight):  # noqa: N803
        return (self.width, self.height)


# ---------------------------------------------------------------------------
# Cover page (drawn entirely on canvas for pixel control)
# ---------------------------------------------------------------------------
def _draw_cover(c, recipe: dict, brand: str, accent: tuple) -> None:
    """Dark gold-accented cover card matching the listing image hero."""
    cx = PAGE_W / 2
    acc = _C(accent)
    acc_light = _C((min(255, accent[0] + 40), min(255, accent[1] + 40), min(255, accent[2] + 30)))
    cream = CREAM_C
    gold_dark = GOLD_DARK_C

    # background
    c.setFillColor(DARK_C)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # inset gold frame + corner ticks
    inset = 22
    c.setStrokeColor(acc); c.setLineWidth(0.9)
    c.rect(inset, inset, PAGE_W - 2 * inset, PAGE_H - 2 * inset, stroke=1, fill=0)
    c.setLineWidth(1.6)
    t = 26
    for x0, y0, dx, dy in ((inset, inset, 1, 1), (PAGE_W - inset, inset, -1, 1),
                           (inset, PAGE_H - inset, 1, -1), (PAGE_W - inset, PAGE_H - inset, -1, -1)):
        c.line(x0, y0, x0 + dx * t, y0)
        c.line(x0, y0, x0, y0 + dy * t)

    def centre(text, y, font, size, color):
        c.setFillColor(color)
        c.setFont(font, size)
        c.drawCentredString(cx, y, text)

    # kicker
    c.setFillColor(acc)
    c.setFont(LATO_BLACK, 10.5)
    c.drawCentredString(cx, PAGE_H - 118, "D I Y   F R A G R A N C E   R E C I P E")
    # name (shrink to fit — longest generated names must never overflow)
    name = recipe["recipe_name"]
    size = 42
    while size > 20 and pdfmetrics.stringWidth(name, PLAYFAIR_BLACK, size) > CONTENT_W - 60:
        size -= 2
    centre(name, PAGE_H - 172, PLAYFAIR_BLACK, size, cream)
    # gold divider
    c.setStrokeColor(acc); c.setLineWidth(1.2)
    dw = 74
    c.line(cx - dw, PAGE_H - 192, cx + dw, PAGE_H - 192)
    # category tagline
    tagline = CATEGORY_TAGLINE.get(recipe["category"], CATEGORY_LABEL.get(recipe["category"], "Fragrance"))
    centre(tagline, PAGE_H - 218, CORMORANT_IT, 16.5, acc_light)

    # scent-bottle motif
    _draw_bottle(c, cx, PAGE_H - 300, scale=1.0, accent=acc, gold_dark=gold_dark)

    # chips: difficulty + price
    diff = DIFFICULTY_LABEL.get(recipe["difficulty"], recipe["difficulty"])
    price = f"${recipe['price_usd']:.2f}".rstrip("0").rstrip(".")
    if not price.startswith("$"):
        price = "$" + price
    chip_y = PAGE_H - 372
    chip_h = 26
    chips = [diff.upper(), f"{price} USD".upper()]
    widths = [pdfmetrics.stringWidth(s, LATO_BOLD, 8.8) + 30 for s in chips]
    gap = 14
    total = sum(widths) + gap
    x = cx - total / 2
    for label, w in zip(chips, widths):
        c.setStrokeColor(acc); c.setLineWidth(0.9)
        c.roundRect(x, chip_y, w, chip_h, chip_h / 2, stroke=1, fill=0)
        c.setFillColor(acc_light); c.setFont(LATO_BOLD, 8.8)
        c.drawCentredString(x + w / 2, chip_y + chip_h / 2 - 3, label)
        x += w + gap

    # theme / holiday pills (gold-filled)
    pills = [p for p in (recipe.get("holiday"), recipe.get("theme")) if p]
    if pills:
        py = chip_y - 42
        pw = [pdfmetrics.stringWidth(p, LATO_BOLD, 9.2) + 34 for p in pills]
        total = sum(pw) + 12 * (len(pills) - 1)
        x = cx - total / 2
        for label, w in zip(pills, pw):
            c.setFillColor(acc)
            c.roundRect(x, py, w, 24, 12, stroke=0, fill=1)
            c.setFillColor(DARK_C); c.setFont(LATO_BOLD, 9.2)
            c.drawCentredString(x + w / 2, py + 7.5, label.upper())
            x += w + 12

    # stats: yield + cost to make
    sy = PAGE_H - 462
    stat_gap = 220
    c.setFillColor(gold_dark); c.setFont(LATO_BOLD, 8.6)
    c.drawCentredString(cx - stat_gap / 2, sy, "Y I E L D")
    c.drawCentredString(cx + stat_gap / 2, sy, "C O S T   T O   M A K E")
    c.setFillColor(cream); c.setFont(CORMORANT_MED, 16)
    c.drawCentredString(cx - stat_gap / 2, sy - 24, recipe["yield"])
    c.drawCentredString(cx + stat_gap / 2, sy - 24, recipe["cost_to_make"])
    # small connectors
    c.setStrokeColor(acc); c.setLineWidth(0.7)
    c.line(cx - stat_gap / 2 - 60, sy + 12, cx - stat_gap / 2 + 60, sy + 12)
    c.line(cx + stat_gap / 2 - 60, sy + 12, cx + stat_gap / 2 + 60, sy + 12)

    # brand + digital-download note
    centre(brand, 118, CORMORANT_IT, 17, acc_light)
    c.setFillColor(gold_dark); c.setFont(LATO_BOLD, 7.6)
    c.drawCentredString(cx, 98, "I N S T A N T   D I G I T A L   D O W N L O A D   ·   P R I N T   A T   H O M E")
    c.drawCentredString(cx, 76, "U S   L E T T E R   8 . 5  ×  1 1   I N")


def _draw_bottle(c, cx, cy, scale, accent, gold_dark) -> None:
    """Minimal line-art fragrance bottle: rounded body, neck, cap, droplets."""
    c.saveState()
    c.translate(cx, cy)
    c.scale(scale, scale)
    c.setStrokeColor(accent); c.setLineWidth(1.5)
    c.setFillColor(DARK_C)
    # body
    c.roundRect(-34, -30, 68, 118, 16, stroke=1, fill=0)
    # neck
    c.rect(-11, 88, 22, 26, stroke=1, fill=0)
    # cap
    c.roundRect(-18, 114, 36, 15, 5, stroke=1, fill=0)
    # shoulder accents
    c.setStrokeColor(gold_dark); c.setLineWidth(1.0)
    c.line(-22, 96, -15, 88)
    c.line(22, 96, 15, 88)
    # essence droplets
    c.setFillColor(accent); c.setStrokeColor(accent)
    for i, (dx, dy, r) in enumerate(((26, 26, 3.2), (32, 10, 2.6), (26, -6, 2.0))):
        c.circle(dx, dy, r, stroke=0, fill=1)
    c.restoreState()


# ---------------------------------------------------------------------------
# Interior page background
# ---------------------------------------------------------------------------
def _interior_bg(c, brand: str, accent: tuple) -> None:
    c.setFillColor(CREAM_C)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    acc = _C(accent)
    c.setStrokeColor(acc); c.setLineWidth(1.1)
    c.line(MARGIN, PAGE_H - 40, PAGE_W - MARGIN, PAGE_H - 40)
    c.setFillColor(INK_SOFT_C)
    c.setFont(CORMORANT_IT, 9.5)
    c.drawString(MARGIN, PAGE_H - 50, brand)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 50, "DIY FRAGRANCE RECIPE")


# ---------------------------------------------------------------------------
# Flowable builders
# ---------------------------------------------------------------------------
def _section_header(kicker: str, title: str, accent: tuple, styles: dict) -> List[Flowable]:
    acc = _C(accent)
    return [
        Spacer(1, 4),
        Paragraph(_esc(kicker).upper(), styles["kicker"]),
        Paragraph(_esc(title), styles["title"]),
        HRFlowable(width="100%", thickness=1.0, color=acc, spaceBefore=2, spaceAfter=12),
    ]


def _wrap_text(text: str, font: str, size: float, max_w: float) -> List[str]:
    """Simple greedy word-wrap using ReportLab's metrics (for canvas text)."""
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if pdfmetrics.stringWidth(trial, font, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build_pyramid(recipe: dict, accent: tuple, width: float = 320, height: float = 246) -> Drawing:
    """Vector scent pyramid (three trapezoid bands + labels), brand palette."""
    d = Drawing(width, height)
    cx = width / 2
    band_h = 52
    gap = 12
    base_w, heart_w, top_w = 250, 188, 126
    meta = [
        ("TOP", recipe["scent_profile"]["top_notes"], top_w, PYRAMID_TOP_FILL, PYRAMID_TOP_EDGE, (74, 58, 40), "30%"),
        ("HEART", recipe["scent_profile"]["heart_notes"], heart_w, PYRAMID_HEART_FILL, PYRAMID_HEART_EDGE, (250, 245, 236), "50%"),
        ("BASE", recipe["scent_profile"]["base_notes"], base_w, PYRAMID_BASE_FILL, PYRAMID_BASE_EDGE, (246, 240, 230), "20%"),
    ]
    y = 14
    for label, notes, w, fill, edge, text_rgb, pct in meta:
        half = w / 2
        pts = [cx - half, y, cx - half + 14, y + band_h,
               cx + half - 14, y + band_h, cx + half, y]
        poly = Polygon(pts, strokeColor=_C(edge), fillColor=_C(fill), strokeWidth=1.2)
        d.add(poly)
        # level label (left, inside band)
        d.add(String(cx - half + 12, y + band_h - 17, label,
                     fontName=LATO_BLACK, fontSize=9.5, fillColor=_C(text_rgb)))
        # percentage (right, inside band)
        d.add(String(cx + half - 12, y + band_h - 17, pct,
                     fontName=LATO_BLACK, fontSize=9.5, fillColor=_C(text_rgb),
                     textAnchor="end"))
        # notes, wrapped + centred inside the band
        inner = w - 2 * 46
        note_font = CORMORANT_SEMI
        note_size = 12.0
        note_text = ", ".join(notes)
        lines = _wrap_text(note_text, note_font, note_size, inner)
        if len(lines) > 2:
            note_size = 10.5
            lines = _wrap_text(note_text, note_font, note_size, inner)
        line_h = 15
        start_y = y + band_h - 32
        if len(lines) == 1:
            start_y = y + band_h / 2 - 5
        for i, ln in enumerate(lines):
            d.add(String(cx, start_y - i * (line_h - 1), ln,
                         fontName=note_font, fontSize=note_size,
                         fillColor=_C(text_rgb), textAnchor="middle"))
        y += band_h + gap
    # connecting line between heart and base (join marks)
    d.add(Line(cx - 60, y - 30, cx + 60, y - 30, strokeColor=_C(GOLD_LINE), strokeWidth=0.8))
    d.add(Line(cx - 60, y - 14, cx + 60, y - 14, strokeColor=_C(GOLD_LINE), strokeWidth=0.8))
    return d


def _notes_columns(recipe: dict, styles: dict) -> Table:
    """Right-hand legend: level, colour swatch, note names."""
    rows = []
    level_names = {
        "top_notes": ("Top Notes", "first impression", GOLD_LIGHT),
        "heart_notes": ("Heart Notes", "the soul of the scent", GOLD_DARK),
        "base_notes": ("Base Notes", "the foundation", (110, 78, 46)),
    }
    for key, (label, tag, swatch) in level_names.items():
        notes = ", ".join(recipe["scent_profile"][key])
        para = (
            f'<font name="{CORMORANT_BOLD}" size="13.5" color="#{_rgb_hex(INK)}">{_esc(label)}</font>'
            f'<br/><font name="{LATO_IT}" size="9.5" color="#{_rgb_hex(INK_SOFT)}">{_esc(tag)}</font>'
            f'<br/><font name="{LATO_REG}" size="10.6" color="#{_rgb_hex(INK)}">{_esc(notes)}</font>'
        )
        rows.append([
            Paragraph("", styles["body"]),
            Paragraph(para, styles["body"]),
        ])
    rows.append([Paragraph("", styles["body"]),
                 Paragraph(
                     f'<font name="{LATO_BOLD}" size="8.6" color="#{_rgb_hex(GOLD_DARK)}">BALANCED '
                     f'30% TOP · 50% HEART · 20% BASE</font>', styles["note"])])
    t = Table(rows, colWidths=[14, 160])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -2), _C(PYRAMID_TOP_FILL)),
        ("BACKGROUND", (0, 1), (0, 1), _C(PYRAMID_HEART_FILL)),
        ("BACKGROUND", (0, 2), (0, 2), _C(PYRAMID_BASE_FILL)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _rgb_hex(rgb) -> str:
    return "%02x%02x%02x" % tuple(rgb)


def _ingredients_table(recipe: dict, styles: dict) -> Table:
    header = [Paragraph(f'<font name="{LATO_BLACK}" size="8.2" color="#ffffff">{h}</font>', styles["note"])
              for h in ("#", "INGREDIENT", "AMOUNT", "PURPOSE")]
    body_rows = [header]
    for i, ing in enumerate(recipe["ingredients"], 1):
        body_rows.append([
            Paragraph(f'<font name="{LATO_BOLD}" size="9.5" color="#{_rgb_hex(INK_SOFT)}">{i}</font>',
                      styles["note"]),
            Paragraph(f'<font name="{LATO_BOLD}" size="10.2" color="#{_rgb_hex(INK)}">{_esc(ing["name"])}</font>',
                      styles["ing-name"]),
            Paragraph(f'<font name="{LATO_REG}" size="10.2" color="#{_rgb_hex(INK)}">{_esc(ing["amount"])}</font>',
                      styles["ing-amount"]),
            Paragraph(
                f'<font name="{LATO_BOLD}" size="9.3" color="#{_rgb_hex(PURPOSE_META[ing["purpose"]][1])}">'
                f'●</font>  <font name="{LATO_BOLD}" size="9.3" color="#{_rgb_hex(INK)}">'
                f'{_esc(PURPOSE_META[ing["purpose"]][0])}</font>',
                styles["ing-purpose"]),
        ])
    t = Table(body_rows, colWidths=[26, 220, 96, 162], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_C),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.6, GOLD_LINE_C),
        ("BOX", (0, 0), (-1, -1), 1.0, GOLD_LINE_C),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, CREAM_DEEP_C]),
    ]
    t.setStyle(TableStyle(style))
    return t


def _equipment_table(equipment: list, styles: dict) -> Table:
    items = [f'<font name="{LATO_BOLD}" size="10.2" color="#{_rgb_hex(GOLD_DARK)}">●</font>'
             f'&nbsp;&nbsp;{_esc(x)}' for x in equipment]
    if len(items) % 2:
        items.append("")
    left, right = items[::2], items[1::2]
    rows = [[Paragraph(a, styles["eq-item"]), Paragraph(b, styles["eq-item"])]
            for a, b in zip(left, right)]
    t = Table(rows, colWidths=[CONTENT_W / 2 - 6, CONTENT_W / 2 - 6])
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    t.setStyle(TableStyle(st))
    return t


def _step_cell(number: int, accent: tuple) -> Table:
    acc = _C(accent)
    t = Table([[str(number)]], colWidths=[26], rowHeights=[26])
    t.setStyle(TableStyle([
        ("ROUNDEDCORNERS", [13, 13, 13, 13]),
        ("BACKGROUND", (0, 0), (-1, -1), acc),
        ("TEXTCOLOR", (0, 0), (-1, -1), WHITE_C),
        ("FONTNAME", (0, 0), (-1, -1), PLAYFAIR_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 12.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _steps_block(recipe: dict, accent: tuple, styles: dict) -> list:
    flow: list = []
    for i, step in enumerate(recipe["instructions"], 1):
        row = Table([[_step_cell(i, accent),
                      Paragraph(f'<font name="{LATO_REG}" size="10.6" '
                                f'color="#{_rgb_hex(INK)}">{_esc(step)}</font>', styles["step"])]],
                     colWidths=[42, CONTENT_W - 42])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        flow.append(row)
        if i != len(recipe["instructions"]):
            flow.append(Spacer(1, 11))
    return flow


def _safety_badge(accent: tuple) -> Table:
    acc = _C(accent)
    t = Table([["!"]], colWidths=[19], rowHeights=[19])
    t.setStyle(TableStyle([
        ("ROUNDEDCORNERS", [9.5, 9.5, 9.5, 9.5]),
        ("BACKGROUND", (0, 0), (-1, -1), acc),
        ("TEXTCOLOR", (0, 0), (-1, -1), WHITE_C),
        ("FONTNAME", (0, 0), (-1, -1), LATO_BLACK),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _safety_panel(recipe: dict, accent: tuple, styles: dict) -> Table:
    """Stand-out safety panel: pale amber, gold border, ! badges per line."""
    inner_rows: list = []
    head = Table(
        [[_safety_badge(accent),
          Paragraph(f'<font name="{CORMORANT_BOLD}" size="13.5" '
                    f'color="#{_rgb_hex(GOLD_DARK)}">BEFORE YOU BEGIN — PLEASE READ</font>',
                    styles["panel-title"])]],
        colWidths=[34, CONTENT_W - 2 * 26 - 34])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    inner_rows.append(head)
    inner_rows.append([Paragraph("", styles["note"])])
    for note in recipe["safety_notes"]:
        row = Table(
            [[_safety_badge(accent),
              Paragraph(f'<font name="{LATO_REG}" size="10.3" '
                        f'color="#{_rgb_hex(INK)}">{_esc(note)}</font>', styles["safety-item"])]],
            colWidths=[34, CONTENT_W - 2 * 26 - 34])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        inner_rows.append(row)

    inner = Table([[r] for r in inner_rows], colWidths=[CONTENT_W - 2 * 26])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    panel = Table([[inner]], colWidths=[CONTENT_W])
    panel.setStyle(TableStyle([
        ("ROUNDEDCORNERS", [10, 10, 10, 10]),
        ("BACKGROUND", (0, 0), (-1, -1), SAFETY_BG),
        ("BOX", (0, 0), (-1, -1), 1.6, _C(accent)),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 26),
        ("RIGHTPADDING", (0, 0), (-1, -1), 26),
    ]))
    return panel


def _stat_tiles(recipe: dict, styles: dict) -> Table:
    diff = DIFFICULTY_LABEL.get(recipe["difficulty"], recipe["difficulty"])
    cost = recipe["cost_to_make"]
    tiles = [
        ("DIFFICULTY", diff),
        ("BATCH SIZE", recipe["yield"]),
        ("COST TO MAKE", cost),
    ]
    rows = []
    for label, value in tiles:
        rows.append([
            Paragraph(f'<font name="{LATO_BOLD}" size="8.4" color="#{_rgb_hex(GOLD_DARK)}">'
                      f'{_esc(label.upper())}</font>', styles["stat-label"]),
            Paragraph(f'<font name="{LATO_REG}" size="10.6" color="#{_rgb_hex(INK)}">'
                      f'{_esc(value)}</font>', styles["stat-value"]),
        ])
    t = Table(rows, colWidths=[CONTENT_W / 3 - 8] * 3)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, GOLD_LINE_C),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, GOLD_LINE_C),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------
def _build_story(recipe: dict, brand: str, accent: tuple) -> list:
    st = _styles()
    story: list = []
    story.append(NextPageTemplate("interior"))
    story.append(PageBreak())          # page 1 = cover (canvas-drawn)

    # --- page 2: scent profile ---------------------------------------------
    story.extend(_section_header("Scent Profile", recipe["recipe_name"], accent, st))
    top = ", ".join(recipe["scent_profile"]["top_notes"])
    heart = ", ".join(recipe["scent_profile"]["heart_notes"])
    base = ", ".join(recipe["scent_profile"]["base_notes"])
    intro = (
        f"A balanced DIY blend that opens with <b>{_esc(top)}</b>, unfolds through "
        f"<b>{_esc(heart)}</b>, and lingers on <b>{_esc(base)}</b>. Every amount is "
        f"measured for a single batch of {_esc(recipe['yield'])} with a classic "
        f"30% top / 50% heart / 20% base structure — the proportions professional "
        f"perfumers use for a scent that wears well from first spray to dry-down."
    )
    story.append(Paragraph(intro, st["body"]))
    story.append(Spacer(1, 14))
    story.append(KeepTogether(Table(
        [[_DrawingFlowable(build_pyramid(recipe, accent)),
          _notes_columns(recipe, st)]],
        colWidths=[330, 174])))
    story.append(Spacer(1, 22))
    story.append(HRFlowable(width="100%", thickness=0.7, color=_C(GOLD_LINE), spaceAfter=10))
    desc = (
        f"<b>Wearing it.</b> This {_esc(CATEGORY_LABEL.get(recipe['category'], 'fragrance').lower())} "
        f"was designed to be worn close, in layers that develop over about four hours — "
        f"top notes arrive first, the heart carries the blend, and the base keeps the "
        f"scent company through the day. Hands-on time is roughly 15–20 minutes."
    )
    story.append(Paragraph(desc, st["body"]))

    # --- page 3: ingredients + equipment ------------------------------------
    story.append(PageBreak())
    story.extend(_section_header("Ingredients & Equipment", "What You'll Need", accent, st))
    story.append(_ingredients_table(recipe, st))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<i>Amounts are for one batch ({_esc(recipe['yield'])}). All ingredients are "
        f"readily available from essential-oil and craft suppliers.</i>", st["note"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph(
        f'<font name="{CORMORANT_BOLD}" size="12.5" color="#{_rgb_hex(GOLD_DARK)}">'
        f'YOU WILL ALSO NEED</font>', st["kicker"]))
    story.append(Spacer(1, 4))
    story.append(_equipment_table(recipe["equipment"], st))
    story.append(Spacer(1, 18))
    cost = Table([[
        Paragraph(f'<font name="{CORMORANT_BOLD}" size="12" color="#{_rgb_hex(GOLD_DARK)}">'
                  f'COST TO MAKE</font>&nbsp;&nbsp;'
                  f'<font name="{LATO_BOLD}" size="12.5" color="#{_rgb_hex(INK)}">'
                  f'{_esc(recipe["cost_to_make"])}</font>', st["body"]),
    ]], colWidths=[CONTENT_W])
    cost.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _C((246, 240, 228))),
        ("BOX", (0, 0), (-1, -1), 1.0, _C(GOLD_LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(cost)

    # --- page 4: instructions -------------------------------------------------
    story.append(PageBreak())
    story.extend(_section_header(
        "Step-by-Step Instructions", f"How to Make Your {recipe['recipe_name']}", accent, st))
    story.extend(_steps_block(recipe, accent, st))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f'<font name="{LATO_IT}" size="10.2" color="#{_rgb_hex(INK_SOFT)}">Tip: read every '
        f'step once before you start, and label your finished {_esc(CATEGORY_LABEL.get(recipe["category"], "creation").lower())} '
        f'with the date you made it.</font>', st["body"]))

    # --- page 5: safety ---------------------------------------------------------
    story.append(PageBreak())
    story.extend(_section_header("Safety Notes", "Craft Safely, Wear Confidently", accent, st))
    story.append(Paragraph(
        "Essential oils are concentrated plant extracts — a little care goes a long way. "
        "Read the panel below before you begin, and keep this card somewhere handy.", st["body"]))
    story.append(Spacer(1, 8))
    story.append(_safety_panel(recipe, accent, st))
    story.append(Spacer(1, 20))
    story.append(_stat_tiles(recipe, st))
    story.append(Spacer(1, 22))
    story.append(Paragraph(
        f'<font name="{CORMORANT_IT}" size="14" color="#{_rgb_hex(GOLD_DARK)}">'
        f'Enjoy your handcrafted {_esc(CATEGORY_LABEL.get(recipe["category"], "fragrance").lower())} — '
        f'happy blending!</font>', ParagraphStyle("closing", alignment=TA_CENTER)))
    return story


def generate_pdf(recipe: dict, out_dir: str | Path, brand: str = "Fragrance Bot") -> Path:
    """Render one recipe JSON to ``<out_dir>/<slug>.pdf``.

    Returns the path of the written PDF. Deterministic: identical recipe +
    brand => byte-identical output.
    """
    assert_valid(recipe)
    register_all()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{recipe['slug']}.pdf"

    accent = accent_for_theme(recipe.get("theme"))
    brand = brand or "Fragrance Bot"

    doc = BaseDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=FRAME_TOP, bottomMargin=FRAME_BOTTOM,
        title=recipe.get("full_title", recipe["recipe_name"]),
        author=brand,
        subject="DIY Fragrance Recipe — digital download",
        creator=f"{brand} · Fragrance Bot PDF generator",
        producer="Fragrance Bot",
        allowSplitting=1,
    )
    # frames / templates
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover")  # unused; cover is canvas-drawn
    interior_frame = Frame(MARGIN, FRAME_BOTTOM, CONTENT_W, FRAME_TOP - FRAME_BOTTOM, id="interior")

    def _cover_page(canv, _doc):
        _draw_cover(canv, recipe, brand, accent)

    def _interior_page(canv, _doc):
        _interior_bg(canv, brand, accent)

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_cover_page),
        PageTemplate(id="interior", frames=[interior_frame], onPage=_interior_page),
    ])

    class _Canvas(_NumberedCanvas):
        pass

    def _canvas_maker(*args, **kwargs):
        c = _Canvas(*args, **kwargs)
        c.set_fb_meta(brand, accent)
        return c

    story = _build_story(recipe, brand, accent)
    doc.build(story, canvasmaker=_canvas_maker)
    return out_path


def pdf_byte_digest(path: str | Path) -> str:
    """SHA-256 of the PDF bytes (determinism check helper)."""
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()