"""Small geometry helpers.

Work zones are a few thousand feet long at most, so a local equirectangular projection centered on
the site is accurate to well under a foot. That keeps the math simple and dependency-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import LatLon

FT_PER_M = 3.280839895
EARTH_R_FT = 6_371_008.8 * FT_PER_M


@dataclass(frozen=True)
class LocalFrame:
    """Planar frame in feet: x = east, y = north, origin at (lat0, lon0)."""

    lat0: float
    lon0: float

    def to_xy(self, p: LatLon) -> tuple[float, float]:
        x = math.radians(p.lon - self.lon0) * EARTH_R_FT * math.cos(math.radians(self.lat0))
        y = math.radians(p.lat - self.lat0) * EARTH_R_FT
        return x, y

    def to_latlon(self, x: float, y: float) -> LatLon:
        lat = self.lat0 + math.degrees(y / EARTH_R_FT)
        lon = self.lon0 + math.degrees(x / (EARTH_R_FT * math.cos(math.radians(self.lat0))))
        return LatLon(lat=lat, lon=lon)


class Centerline:
    """A polyline in local feet with stationing (distance along the line from its start)."""

    def __init__(self, points: list[LatLon], frame: LocalFrame | None = None, median: list[tuple[float, float]] | None = None):
        """``median``: optional [(station_ft, width_ft)] profile of a divided road's median. Lanes on
        each side are pushed out by half the median width at that station, so plans follow
        carriageways that split apart around medians."""
        if len(points) < 2:
            raise ValueError("centerline needs at least two points")
        self.frame = frame or LocalFrame(points[0].lat, points[0].lon)
        self.xy = [self.frame.to_xy(p) for p in points]
        self.cum = [0.0]
        for (x0, y0), (x1, y1) in zip(self.xy, self.xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(x1 - x0, y1 - y0))
        if self.length <= 0:
            raise ValueError("centerline has zero length")
        self.median = sorted((float(s), max(0.0, float(w))) for s, w in (median or []))

    @classmethod
    def for_road(cls, road) -> "Centerline":
        return cls(road.centerline, median=[(m.station_ft, m.width_ft) for m in getattr(road, "median", []) or []])

    def median_half(self, station: float) -> float:
        """Half the median width (ft) at a station (linear between profile points, flat past the ends)."""
        m = self.median
        if not m:
            return 0.0
        if station <= m[0][0]:
            return m[0][1] / 2
        for (s0, w0), (s1, w1) in zip(m, m[1:]):
            if station <= s1:
                t = (station - s0) / ((s1 - s0) or 1.0)
                return (w0 + (w1 - w0) * t) / 2
        return m[-1][1] / 2

    @property
    def length(self) -> float:
        return self.cum[-1]

    def _segment(self, station: float) -> int:
        for i in range(len(self.cum) - 1):
            if station <= self.cum[i + 1]:
                return i
        return len(self.cum) - 2

    def heading(self, station: float) -> tuple[float, float]:
        """Unit vector of the forward direction at a station (extends past the ends)."""
        i = self._segment(min(max(station, 0.0), self.length))
        (x0, y0), (x1, y1) = self.xy[i], self.xy[i + 1]
        d = math.hypot(x1 - x0, y1 - y0) or 1.0
        return (x1 - x0) / d, (y1 - y0) / d

    def point_xy(self, station: float, offset: float = 0.0) -> tuple[float, float]:
        """Point at a station, offset to the right (+) or left (-) of the forward direction.

        Stations beyond either end are extrapolated along the end segment, so advance warning
        signs can be placed even if the drawn centerline is short.
        """
        clamped = min(max(station, 0.0), self.length)
        i = self._segment(clamped)
        (x0, y0), (x1, y1) = self.xy[i], self.xy[i + 1]
        seg = self.cum[i + 1] - self.cum[i] or 1.0
        t = (station - self.cum[i]) / seg
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        if offset and self.median:
            offset += math.copysign(self.median_half(station), offset)
        # right-hand normal of (ux, uy) is (uy, -ux)
        return x + uy * offset, y - ux * offset

    def point(self, station: float, offset: float = 0.0) -> LatLon:
        return self.frame.to_latlon(*self.point_xy(station, offset))

    def bearing_deg(self, station: float) -> float:
        """Compass bearing (0 = north, clockwise) of the forward direction."""
        ux, uy = self.heading(station)
        return (math.degrees(math.atan2(ux, uy)) + 360.0) % 360.0

    def project(self, p: LatLon) -> tuple[float, float]:
        """Return (station, signed lane offset) of the closest point on the line (offset + = right).

        Stations extend past either end (points beyond the drawn line get negative or > length
        stations), and the offset excludes the median, matching ``point``."""
        px, py = self.frame.to_xy(p)
        best = (float("inf"), 0.0, 0.0)
        last = len(self.xy) - 2
        for i, ((x0, y0), (x1, y1)) in enumerate(zip(self.xy, self.xy[1:])):
            dx, dy = x1 - x0, y1 - y0
            seg2 = dx * dx + dy * dy or 1.0
            t = ((px - x0) * dx + (py - y0) * dy) / seg2
            t = max(float("-inf") if i == 0 else 0.0, min(float("inf") if i == last else 1.0, t))
            cx, cy = x0 + dx * t, y0 + dy * t
            dist = math.hypot(px - cx, py - cy)
            if dist < best[0]:
                seg = math.sqrt(seg2)
                # cross product sign: positive when the point is to the left
                cross = (dx * (py - y0) - dy * (px - x0)) / seg
                best = (dist, self.cum[i] + t * seg, -cross)
        station, off = best[1], best[2]
        if self.median:
            half = self.median_half(station)
            off = 0.0 if abs(off) <= half else off - math.copysign(half, off)
        return station, off

    def strip(self, s0: float, s1: float, off0: float, off1: float, steps: int = 8) -> list[LatLon]:
        """Polygon covering stations s0..s1 between two offsets (for zones)."""
        n = max(2, steps)
        fwd = [self.point(s0 + (s1 - s0) * k / (n - 1), off0) for k in range(n)]
        back = [self.point(s1 - (s1 - s0) * k / (n - 1), off1) for k in range(n)]
        return fwd + back


def haversine_ft(a: LatLon, b: LatLon) -> float:
    la1, la2 = math.radians(a.lat), math.radians(b.lat)
    dla = la2 - la1
    dlo = math.radians(b.lon - a.lon)
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * EARTH_R_FT * math.asin(math.sqrt(h))
