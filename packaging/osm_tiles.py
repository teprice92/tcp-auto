"""Find road centerlines from OpenStreetMap map tiles (used to build accurate demo streets).

Used only when the OSM data API (Overpass) isn't reachable. OSM's standard map style fills each
road class with a distinct color, so sampling the tile pixels across a road gives the center of
its painted band. Accuracy is about 1 m at zoom 18, which is plenty for placing a demo plan.

Usage is light (a few dozen tiles per demo build, cached on disk), per the OSM tile usage policy.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import httpx
from PIL import Image

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
UA = "tcp-auto-demo-builder/0.1 (FlagPole demo; light use)"
Z = 18
TILE = 256

# OSM Carto road fill colors
COLORS = {
    "motorway": (232, 146, 162), "trunk": (249, 178, 156), "primary": (252, 214, 164),
    "secondary": (247, 250, 191), "tertiary": (255, 255, 255), "residential": (255, 255, 255),
}


def lonlat_to_px(lat: float, lon: float, z: int = Z) -> tuple[float, float]:
    n = TILE * 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def px_to_lonlat(x: float, y: float, z: int = Z) -> tuple[float, float]:
    n = TILE * 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


class TileCache:
    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mem: dict[tuple[int, int], Image.Image] = {}
        self.client = httpx.Client(timeout=30, headers={"User-Agent": UA})

    def tile(self, tx: int, ty: int) -> Image.Image:
        key = (tx, ty)
        if key not in self.mem:
            f = self.dir / f"{Z}_{tx}_{ty}.png"
            if not f.exists():
                r = self.client.get(TILE_URL.format(z=Z, x=tx, y=ty))
                r.raise_for_status()
                f.write_bytes(r.content)
            self.mem[key] = Image.open(io.BytesIO(f.read_bytes())).convert("RGB")
        return self.mem[key]

    def pixel(self, x: float, y: float) -> tuple[int, int, int]:
        tx, ty = int(x // TILE), int(y // TILE)
        return self.tile(tx, ty).getpixel((int(x) % TILE, int(y) % TILE))


def _match(c, target, tol=10) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(c, target))


def band_center(cache: TileCache, x0: float, y0: float, dx: float, dy: float, color, search_px: int = 120, min_run: int = 6, merge_gap: int = 30):
    """Scan from (x0,y0) along unit direction (dx,dy) for ±search_px; return the center offset of the
    contiguous run of `color` closest to 0, or None."""
    hits = [t for t in range(-search_px, search_px + 1) if _match(cache.pixel(x0 + dx * t, y0 + dy * t), color)]
    runs, cur = [], []
    for t in hits:
        if cur and t != cur[-1] + 1:
            runs.append(cur)
            cur = []
        cur.append(t)
    if cur:
        runs.append(cur)
    # Merge runs split by a thin gap: divided roads (two carriageways), center lines, label strokes
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][-1] <= merge_gap:
            merged[-1] = merged[-1] + r
        else:
            merged.append(list(r))
    merged = [r for r in merged if len(r) >= min_run]
    if not merged:
        return None
    best = min(merged, key=lambda r: abs((r[0] + r[-1]) / 2))
    return (best[0] + best[-1]) / 2, best[-1] - best[0] + 1


def trace_road(cache: TileCache, lat: float, lon: float, orientation: str, length_m: float, color, step_m: float = 60.0, straight: bool = True):
    """Trace an E-W ('ew') or N-S ('ns') road through (lat, lon) for length_m total. Returns [(lat, lon)]."""
    x, y = lonlat_to_px(lat, lon)
    m_per_px = 156543.03392 * math.cos(math.radians(lat)) / 2 ** Z
    steps = int(length_m / step_m / 2)
    pts = []
    for k in range(-steps, steps + 1):
        if orientation == "ew":
            sx, sy = x + k * step_m / m_per_px, y
            found = band_center(cache, sx, sy, 0, 1, color)
            if found:
                pts.append(px_to_lonlat(sx, sy + found[0]))
        else:
            sx, sy = x, y + k * step_m / m_per_px
            found = band_center(cache, sx, sy, 1, 0, color)
            if found:
                pts.append(px_to_lonlat(sx + found[0], sy))
    if straight and len(pts) >= 3:
        return fit_line(pts, orientation, m_per_px)
    return pts


def fit_line(pts, orientation: str, m_per_px: float, max_resid_m: float = 2.5):
    """Least-squares straight line through the samples, dropping outliers (labels, crossings)."""
    # ew: lat = a + b*lon ; ns: lon = a + b*lat
    xs = [p[1] if orientation == "ew" else p[0] for p in pts]
    ys = [p[0] if orientation == "ew" else p[1] for p in pts]
    keep = list(range(len(pts)))
    deg_per_m = 1 / 111_000
    for _ in range(4):
        n = len(keep)
        mx = sum(xs[i] for i in keep) / n
        my = sum(ys[i] for i in keep) / n
        sxx = sum((xs[i] - mx) ** 2 for i in keep) or 1e-12
        b_ = sum((xs[i] - mx) * (ys[i] - my) for i in keep) / sxx
        a_ = my - b_ * mx
        resid = {i: abs(ys[i] - (a_ + b_ * xs[i])) for i in keep}
        new = [i for i in keep if resid[i] <= max_resid_m * deg_per_m]
        if len(new) == len(keep) or len(new) < 3:
            break
        keep = new
    lo, hi = min(xs), max(xs)
    ends = [(lo, a_ + b_ * lo), (hi, a_ + b_ * hi)]
    return [(y, x) if orientation == "ew" else (x, y) for x, y in ends]


def cross_road(cache: TileCache, lat: float, lon: float, orientation: str, color, search_px: int = 200):
    """Find the center of a crossing road near (lat, lon). orientation is the crossing road's ('ns' or 'ew')."""
    x, y = lonlat_to_px(lat, lon)
    if orientation == "ns":
        found = band_center(cache, x, y, 1, 0, color, search_px)
        return px_to_lonlat(x + found[0], y) if found else None
    found = band_center(cache, x, y, 0, 1, color, search_px)
    return px_to_lonlat(x, y + found[0]) if found else None


def cross_road_line(cache: TileCache, lat: float, lon: float, color, length_m: float = 300):
    """A crossing N-S road near (lat, lon), traced and fitted (samples avoid the main road itself)."""
    return trace_road(cache, lat, lon, "ns", length_m, color, step_m=30)


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i - 1))
            start = None
    return runs


def carriageway_profile(cache: TileCache, line, color, step_m: float = 12.0, search_px: int = 90, min_gap_px: int = 3):
    """Walk along a fitted E-W centerline and measure how far apart the two directions' carriageways are.

    Returns [(lon, center_lat, carriageway_separation_m)] per sample (0 = one undivided road). Dark pixels
    (street-name lettering) count as road so labels don't look like medians. Two cases mean a median:
      * two road bands with a gap of other colors between them, and
      * one band clearly wider than a single carriageway: where a road starts to split (or has a narrow
        median / turn bay) the map draws both carriageways overlapping as one wide band.
    Map styles draw roads wider than real life, so band *centers* are reliable but band edges are not."""
    (lat0, lon0), (lat1, lon1) = line
    x0, y0 = lonlat_to_px(lat0, lon0)
    x1, y1 = lonlat_to_px(lat1, lon1)
    m_per_px = 156543.03392 * math.cos(math.radians(lat0)) / 2 ** Z
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) * m_per_px / step_m))
    samples = []
    for k in range(n + 1):
        x = x0 + (x1 - x0) * k / n
        yc = y0 + (y1 - y0) * k / n
        flags = []
        for t in range(-search_px, search_px + 1):
            c = cache.pixel(x, yc + t)
            flags.append(_match(c, color) or sum(c) < 3 * 110)
        runs = []
        for r in _runs(flags):  # a 1-2 px break (anti-aliased label edge) doesn't split a band
            if runs and r[0] - runs[-1][1] - 1 < min_gap_px:
                runs[-1] = (runs[-1][0], r[1])
            else:
                runs.append(r)
        runs = [r for r in runs if r[1] - r[0] + 1 >= 4]
        if not runs:
            continue
        # keep the band(s) nearest the fitted line: the closest run, plus a partner across a gap
        mid = search_px
        runs.sort(key=lambda r: min(abs(r[0] - mid), abs(r[1] - mid)) if not (r[0] <= mid <= r[1]) else 0)
        first = runs[0]
        partner = None
        for r in runs[1:]:
            gap = (r[0] - first[1] - 1) if r[0] > first[1] else (first[0] - r[1] - 1)
            if min_gap_px <= gap <= 70 and (r[1] - r[0]) >= 0.4 * (first[1] - first[0]):
                partner = r
                break
        samples.append((x, yc, first, partner))
    if not samples:
        return []
    # Width of a single carriageway's band: the typical width of lone bands (lower quartile ignores wide ones)
    widths = sorted(f[1] - f[0] + 1 for _, _, f, p in samples if p is None) or sorted(f[1] - f[0] + 1 for _, _, f, _ in samples)
    single = widths[len(widths) // 4]
    out = []
    for x, yc, first, partner in samples:
        if partner:
            c1, c2 = (first[0] + first[1]) / 2, (partner[0] + partner[1]) / 2
            mid_px, sep_px = (c1 + c2) / 2, abs(c2 - c1)
        else:
            w = first[1] - first[0] + 1
            mid_px = (first[0] + first[1]) / 2
            if w > 3 * single:  # a same-colored cross street or plaza, not a median: skip the sample
                continue
            # carriageway centers sit half a single band in from each edge
            sep_px = (w - single) if w > 1.3 * single else 0.0
        lat_c, lon_c = px_to_lonlat(x, yc - search_px + mid_px)
        out.append((lon_c, lat_c, sep_px * m_per_px))
    return out


def median_profile(cache: TileCache, line, color, tol_ft: float = 4.0) -> list[dict]:
    """carriageway_profile as a compact list of {station_ft, separation_ft} along `line` (station 0 at line[0])."""
    (lat0, lon0), (lat1, lon1) = line
    span = lon1 - lon0
    length_ft = math.dist(*(lonlat_to_px(lat, lon) for lat, lon in line)) * 156543.03392 * math.cos(math.radians(lat0)) / 2 ** Z * 3.28084
    raw = [(round((lon - lon0) / span * length_ft), round(sep * 3.28084, 1)) for lon, _, sep in carriageway_profile(cache, line, color)]
    # running median over 5 samples (~60 m): removes short blips (labels, driveways, turn-bay paint) and jitter
    vals = []
    for i in range(len(raw)):
        win = sorted(v for _, v in raw[max(0, i - 2):i + 3])
        vals.append(win[len(win) // 2])
    # then keep only the points where the value changes
    out = []
    for i, ((st, _), v) in enumerate(zip(raw, vals)):
        prev = out[-1]["separation_ft"] if out else None
        nxt = vals[i + 1] if i + 1 < len(vals) else None
        if prev is None or nxt is None or abs(v - prev) > tol_ft or (v > 0) != (prev > 0) or (v > 0) != (nxt > 0):
            out.append({"station_ft": st, "separation_ft": v})
    return out
