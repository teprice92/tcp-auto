"""PDF ingestion: text spans with coordinates, drawing scale, and regions to ignore.

Vector PDFs exported from CAD carry real text, which is what v1 relies on. Scanned (raster) pages
return no spans; the caller reports that and the user adds work items by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from ..models import PageModel, TextSpan

# 1" = 40'   |   1"=40'-0"   |   SCALE: 1" = 20 FT
_SCALE_INCH = re.compile(r"1\s*(?:\"|”|''|IN\.?)\s*=\s*(\d+(?:\.\d+)?)\s*(?:'|’|FT\.?|FEET)", re.I)
# SCALE 1:480
_SCALE_RATIO = re.compile(r"SCALE\s*:?\s*1\s*:\s*(\d+)", re.I)

NOTE_HEADINGS = re.compile(r"^\s*(GENERAL\s+NOTES|NOTES|CONSTRUCTION\s+NOTES|KEYED\s+NOTES)\s*:?\s*$", re.I)
LEGEND_HEADINGS = re.compile(r"^\s*(LEGEND|SYMBOL\s+LEGEND|SYMBOLS)\s*:?\s*$", re.I)


def parse_scale(text: str) -> float | None:
    """Return feet per inch from a scale note, or None."""
    m = _SCALE_INCH.search(text)
    if m:
        return float(m.group(1))
    m = _SCALE_RATIO.search(text)
    if m:
        return float(m.group(1)) / 12.0
    return None


def _spans(page: fitz.Page, index: int) -> list[TextSpan]:
    out: list[TextSpan] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            size = max((s.get("size", 0.0) for s in line.get("spans", [])), default=0.0)
            out.append(TextSpan(page=index, text=text, bbox=(x0, y0, x1, y1), size=size))
    return out


def _excluded_regions(spans: list[TextSpan], width: float, height: float) -> list[tuple[float, float, float, float]]:
    """Areas whose text is not a work item: notes blocks, legends, and the title block.

    Heuristics:
    - A "NOTES"/"LEGEND" heading excludes the column of text below it (heading x-range widened,
      down to the next big gap or the page bottom).
    - The title block is assumed to be a strip along the right edge (last 18% of width) or the
      bottom edge (last 12% of height), which covers most utility sheet borders.
    """
    regions: list[tuple[float, float, float, float]] = []
    regions.append((width * 0.82, 0.0, width, height))  # right-side title block
    regions.append((0.0, height * 0.88, width, height))  # bottom title strip

    for sp in spans:
        if NOTE_HEADINGS.match(sp.text) or LEGEND_HEADINGS.match(sp.text):
            x0, y0, x1, _ = sp.bbox
            col = sorted(
                (s for s in spans if s.bbox[1] >= y0 and s.bbox[0] >= x0 - 20 and s.bbox[0] <= x1 + 200),
                key=lambda s: s.bbox[1],
            )
            bottom = y0
            right = x1
            for s in col:
                if s.bbox[1] - bottom > 40:  # gap ends the block
                    break
                bottom = max(bottom, s.bbox[3])
                right = max(right, s.bbox[2])
            regions.append((x0 - 4, y0 - 4, right + 4, bottom + 4))
    return regions


def ingest_pdf(path: str | Path) -> list[PageModel]:
    doc = fitz.open(str(path))
    pages: list[PageModel] = []
    try:
        for i, page in enumerate(doc):
            spans = _spans(page, i)
            scale = None
            scale_text = None
            for sp in spans:
                s = parse_scale(sp.text)
                if s:
                    scale, scale_text = s, sp.text
                    break
            pages.append(
                PageModel(
                    page=i,
                    width=page.rect.width,
                    height=page.rect.height,
                    spans=spans,
                    scale_ft_per_inch=scale,
                    scale_text=scale_text,
                    excluded_regions=_excluded_regions(spans, page.rect.width, page.rect.height),
                )
            )
    finally:
        doc.close()
    return pages


def render_page_png(path: str | Path, page: int, zoom: float = 1.5) -> bytes:
    """Render one page to PNG (used by the reference panel in the editor)."""
    doc = fitz.open(str(path))
    try:
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()
