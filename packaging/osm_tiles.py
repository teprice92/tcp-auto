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
