"""Keyword-driven work-item extraction ("Construct" / "Remove" labels).

v1 working assumption: every work item on the drawing is labeled with some form of Construct or
Remove, and the work is next to a road. Everything found here is shown to the user, who can add,
delete, or move items before a plan is generated.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from ..models import Action, ExtractionResult, PageModel, TextSpan, TitleBlockInfo, WorkItem

KEYWORDS_FILE = Path(__file__).with_name("keywords.yaml")

_JOB = re.compile(r"\b(?:W\.?O\.?|WORK\s*ORDER|JOB)\s*(?:NO\.?|#|NUMBER)?\s*[:#]?\s*([A-Z0-9-]{4,})", re.I)
_ADDRESS = re.compile(r"\b(\d{2,6}\s+(?:[NSEW]\.?\s+)?[A-Z0-9][A-Z0-9 .]*?\s(?:ST|STREET|RD|ROAD|AVE|AVENUE|DR|DRIVE|BLVD|WAY|LN|LANE|PKWY|PARKWAY|CT|PL)\b\.?)", re.I)
_STREET = re.compile(r"\b((?:[NSEW]\.?\s+)?[A-Z][A-Z0-9 .]{1,30}?\s(?:ST|STREET|RD|ROAD|AVE|AVENUE|DR|DRIVE|BLVD|WAY|LN|LANE|PKWY|PARKWAY))\b\.?", re.I)


@lru_cache(maxsize=1)
def load_keywords(path: str | None = None) -> dict:
    with open(path or KEYWORDS_FILE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "construct": [re.compile(p, re.I) for p in cfg.get("construct", [])],
        "remove": [re.compile(p, re.I) for p in cfg.get("remove", [])],
        "device_types": {k: re.compile(v, re.I) for k, v in cfg.get("device_types", {}).items()},
        "ignore": [re.compile(p, re.I) for p in cfg.get("ignore_if_matches", [])],
    }


def _inside(x: float, y: float, region: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = region
    return x0 <= x <= x1 and y0 <= y <= y1


def _actions(text: str, kw: dict) -> list[tuple[Action, int]]:
    """Actions mentioned in a line, with the character position of each match."""
    found: list[tuple[Action, int]] = []
    for action, pats in ((Action.construct, kw["construct"]), (Action.remove, kw["remove"])):
        hits = [m.start() for p in pats for m in p.finditer(text)]
        if hits:
            found.append((action, min(hits)))
    return sorted(found, key=lambda a: a[1])


def _device_type(text: str, kw: dict) -> str | None:
    best: tuple[int, str] | None = None
    for name, pat in kw["device_types"].items():
        m = pat.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None


def _label_with_neighbors(span: TextSpan, spans: list[TextSpan]) -> str:
    """Labels are often split over two lines ("CONSTRUCT" / "45' POLE"). Join the line just below."""
    x0, y0, x1, y1 = span.bbox
    h = (y1 - y0) or span.size or 8
    below = [
        s for s in spans
        if s is not span and 0 <= s.bbox[1] - y1 <= h * 0.8 and abs(s.bbox[0] - x0) <= h * 3
    ]
    if below:
        nxt = min(below, key=lambda s: s.bbox[1])
        return f"{span.text} {nxt.text}"
    return span.text


def extract_work_items(pages: list[PageModel], keywords_path: str | None = None) -> ExtractionResult:
    kw = load_keywords(keywords_path)
    items: list[WorkItem] = []
    notes: list[str] = []
    warnings: list[str] = []
    title = TitleBlockInfo()

    for page in pages:
        if not page.spans:
            warnings.append(
                f"Page {page.page + 1} has no readable text (it may be a scan). Add work items by clicking the map."
            )
            continue
        for sp in page.spans:
            cx = (sp.bbox[0] + sp.bbox[2]) / 2
            cy = (sp.bbox[1] + sp.bbox[3]) / 2
            excluded = any(_inside(cx, cy, r) for r in page.excluded_regions)

            # Title block / notes info, collected from excluded areas
            if excluded:
                if not title.job_number and (m := _JOB.search(sp.text)):
                    title.job_number = m.group(1)
                if not title.address and (m := _ADDRESS.search(sp.text)):
                    title.address = m.group(1).strip()
                if _actions(sp.text, kw) or len(sp.text) > 30:
                    notes.append(sp.text)
                continue

            if not title.address and (m := _ADDRESS.search(sp.text)):
                title.address = m.group(1).strip()
            for m in _STREET.finditer(sp.text):
                name = m.group(1).strip().upper()
                if not _actions(name, kw) and name not in title.streets and len(title.streets) < 10:
                    title.streets.append(name)

            acts = _actions(sp.text, kw)
            if not acts:
                continue
            if any(p.search(sp.text) for p in kw["ignore"]):
                notes.append(sp.text)
                continue
            label = _label_with_neighbors(sp, page.spans)
            dtype = _device_type(label, kw)
            for action, _ in acts:
                items.append(
                    WorkItem(
                        action=action,
                        device_type=dtype,
                        label_text=label,
                        page=page.page,
                        x=cx,
                        y=cy,
                        confidence=0.9 if dtype else 0.7,
                    )
                )

    if pages and not items:
        warnings.append('No "Construct" or "Remove" labels were found. Add work items manually.')
    return ExtractionResult(pages=pages, items=items, title_block=title, notes=notes, warnings=warnings)


def item_extent_ft(items: list[WorkItem], page: PageModel) -> float:
    """Spread of the included work items on the sheet, converted to feet using the drawing scale.

    Returns 0 when there is no scale or fewer than two items (the 250 ft minimum then governs).
    """
    pts = [(i.x, i.y) for i in items if i.included and i.page == page.page]
    if len(pts) < 2 or not page.scale_ft_per_inch:
        return 0.0
    xs, ys = zip(*pts)
    span_pts = max(max(xs) - min(xs), max(ys) - min(ys))
    return span_pts / 72.0 * page.scale_ft_per_inch
