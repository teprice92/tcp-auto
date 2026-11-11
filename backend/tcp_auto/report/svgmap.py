"""Plan-view drawing of a TCP as SVG, for the report.

The road is drawn straightened along its centerline (station on the x axis) with lateral distances
exaggerated so lanes and devices are readable on a page. A north arrow shows true orientation.
This works with no map-tile access; the interactive editor shows the same layout on an OSM map.
"""

from __future__ import annotations

import html
import math

from ..geo import Centerline
from ..models import DeviceType, LatLon, ProjectDetails, RoadContext, TcpPlan

W, H = 1000, 370
MARGIN_X = 40
ROAD_Y = 182  # screen y of the centerline


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def render_plan_svg(plan: TcpPlan, road: RoadContext, details: ProjectDetails) -> str:
    cl = Centerline.for_road(road)
    for dv in plan.devices:
        dv.station_ft, dv.offset_ft = (round(v, 1) for v in cl.project(LatLon(lat=dv.lat, lon=dv.lon)))
    stations = [dv.station_ft for dv in plan.devices] + [plan.dimensions.work_start_station_ft, plan.dimensions.work_end_station_ft]
    s_min, s_max = min(stations) - 60, max(stations) + 60
    sx = (W - 2 * MARGIN_X) / max(1.0, s_max - s_min)

    w = road.lane_width_ft
    if road.one_way:
        n = road.lanes_forward + road.lanes_backward
        left_edge, right_edge = -n * w / 2, n * w / 2
    else:
        left_edge, right_edge = -road.lanes_backward * w, road.lanes_forward * w
    road_w = right_edge - left_edge
    sy = 130.0 / max(road_w, 24.0)  # lateral exaggeration: road band ~130 px

    def X(st: float) -> float:
        return MARGIN_X + (st - s_min) * sx

    def Y(off: float) -> float:
        return ROAD_Y + off * sy

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" font-family="Arial, Helvetica, sans-serif">',
        "<defs>"
        '<pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="8" height="8" fill="#fde3c4"/><line x1="0" y1="0" x2="0" y2="8" stroke="#f07c1b" stroke-width="3"/></pattern>'
        "</defs>",
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#f5f8fb"/>',
    ]

    # Cross streets
    for ix in road.intersections:
        if s_min <= ix.station_ft <= s_max:
            x = X(ix.station_ft)
            out.append(f'<rect x="{x - 22:.1f}" y="10" width="44" height="{H - 20}" fill="#cfd6df"/>')
            out.append(f'<text x="{x + 4:.1f}" y="24" font-size="11" fill="#444" transform="rotate(90 {x + 4:.1f} 24)">{_esc(ix.cross_street)}{" (signal)" if ix.signalized else ""}</text>')

    # Sidewalk/shoulder strips and road
    out.append(f'<rect x="{MARGIN_X - 20}" y="{Y(left_edge) - 26:.1f}" width="{W - 2 * MARGIN_X + 40}" height="{road_w * sy + 52:.1f}" fill="#e3e8ee"/>')
    out.append(f'<rect x="{MARGIN_X - 20}" y="{Y(left_edge):.1f}" width="{W - 2 * MARGIN_X + 40}" height="{road_w * sy:.1f}" fill="#6b6f74"/>')
    lanes_total = int(round(road_w / w))
    for k in range(1, lanes_total):
        off = left_edge + k * w
        if not road.one_way and abs(off) < 0.1:
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(0) - 2:.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(0) - 2:.1f}" stroke="#f2c230" stroke-width="2"/>')
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(0) + 2:.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(0) + 2:.1f}" stroke="#f2c230" stroke-width="2"/>')
        else:
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(off):.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(off):.1f}" stroke="#fff" stroke-width="1.5" stroke-dasharray="14 12"/>')

    # Direction arrows
    if not road.one_way:
        out.append(_arrow(MARGIN_X + 10, Y(right_edge - w / 2), 1))
        out.append(_arrow(W - MARGIN_X - 10, Y(left_edge + w / 2), -1))
    else:
        out.append(_arrow(MARGIN_X + 10, Y(0), 1))
    if road.name:
        out.append(f'<text x="{W - MARGIN_X - 6}" y="{Y(right_edge) + 18:.1f}" font-size="13" font-weight="bold" fill="#333" text-anchor="end">{_esc(road.name)}</text>')

    # Zones
    colors = {"buffer": ("#ffffff", 0.35), "taper": ("#f07c1b", 0.25), "reduced_speed": ("#2b6cb0", 0.08)}
    for z in plan.zones:
        if z.kind == "roadway":
            continue
        pts = [cl.project(p) for p in z.polygon]
        path = " ".join(f"{X(s):.1f},{Y(o):.1f}" for s, o in pts)
        if z.kind == "work_area":
            out.append(f'<polygon points="{path}" fill="url(#hatch)" stroke="#c05800" stroke-width="1.5"/>')
        else:
            c, a = colors.get(z.kind, ("#999", 0.2))
            out.append(f'<polygon points="{path}" fill="{c}" fill-opacity="{a}" stroke="none"/>')

    # Devices
    label_rows: dict[int, float] = {}
    for dv in sorted(plan.devices, key=lambda d: d.station_ft or 0):
        x, y = X(dv.station_ft), Y(dv.offset_ft)
        t = dv.type
        if t == DeviceType.cone:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="#f36f21" stroke="#7a2e00" stroke-width="0.6"/>')
        elif t == DeviceType.drum:
            out.append(f'<rect x="{x - 3.5:.1f}" y="{y - 3.5:.1f}" width="7" height="7" fill="#f36f21" stroke="#fff" stroke-width="1"/>')
        elif t == DeviceType.barricade3:
            out.append(f'<rect x="{x - 8:.1f}" y="{y - 3:.1f}" width="16" height="6" fill="#fff" stroke="#f36f21" stroke-width="2"/>')
        elif t == DeviceType.truck:
            out.append(f'<rect x="{x - 40 * sx / 2:.1f}" y="{y - 9:.1f}" width="{40 * sx:.1f}" height="18" rx="2" fill="#ffffff" stroke="#1a365d" stroke-width="1.5"/>')
            out.append(f'<text x="{x:.1f}" y="{y + 3:.1f}" font-size="8" text-anchor="middle" fill="#1a365d">T{(dv.label or "").split()[-1]}</text>')
        elif t == DeviceType.arrow_board:
            out.append(f'<rect x="{x - 12:.1f}" y="{y - 7:.1f}" width="24" height="14" fill="#111"/>')
            out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" font-size="10" text-anchor="middle" fill="#ffcc00">{"&#8592;" if (dv.offset_ft or 0) > 0 else "&#8594;"}</text>')
        elif t in (DeviceType.flagger, DeviceType.police):
            color = "#d62828" if t == DeviceType.flagger else "#1d4ed8"
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{color}" stroke="#fff" stroke-width="1.5"/>')
            out.append(f'<text x="{x:.1f}" y="{y + 3.5:.1f}" font-size="10" font-weight="bold" text-anchor="middle" fill="#fff">{"F" if t == DeviceType.flagger else "P"}</text>')
        elif t == DeviceType.light_tower:
            out.append(f'<polygon points="{x:.1f},{y - 7:.1f} {x + 6:.1f},{y + 5:.1f} {x - 6:.1f},{y + 5:.1f}" fill="#ffd60a" stroke="#555" stroke-width="0.8"/>')
        elif t == DeviceType.sign:
            fill = "#f36f21" if (dv.code or "").startswith("W") else ("#ffffff" if (dv.code or "").startswith(("R", "G")) else "#f36f21")
            if (dv.code or "").startswith("G"):
                fill = "#f36f21"
            out.append(f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" fill="{fill}" stroke="#222" stroke-width="1" transform="rotate(45 {x:.1f} {y:.1f})"/>')
            # stagger labels so neighbouring signs don't collide
            above = (dv.offset_ft or 0) < 0
            row = 0
            key = int(x // 70)
            while label_rows.get(key * 10 + row + (0 if above else 5), -1e9) > x - 70 and row < 3:
                row += 1
            label_rows[key * 10 + row + (0 if above else 5)] = x
            ly = y - 12 - row * 12 if above else y + 20 + row * 12
            out.append(f'<text x="{x:.1f}" y="{ly:.1f}" font-size="10" text-anchor="middle" fill="#222" font-weight="bold">{_esc(dv.code or "")}</text>')

    # Dimension callouts (affected direction)
    dims = plan.dimensions
    d = 1 if dims.work_end_station_ft >= dims.work_start_station_ft else -1
    ws = dims.work_start_station_ft
    near_edge = right_edge if (plan.devices and any(dv.group == "work" and (dv.offset_ft or 0) > 0 for dv in plan.devices)) else left_edge
    yb = Y(near_edge) + (52 if near_edge > 0 else -52)
    segs = [
        (ws - d * (dims.buffer_ft + dims.taper_ft), ws - d * dims.buffer_ft, f"Taper {dims.taper_ft:.0f}'"),
        (ws - d * dims.buffer_ft, ws, f"Buffer {dims.buffer_ft:.0f}'"),
        (ws, dims.work_end_station_ft, f"Work area {dims.work_area_ft:.0f}'"),
    ]
    for a, b, text in segs:
        xa, xb = sorted((X(a), X(b)))
        out.append(f'<line x1="{xa:.1f}" y1="{yb:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" stroke="#333" stroke-width="1"/>')
        for xx in (xa, xb):
            out.append(f'<line x1="{xx:.1f}" y1="{yb - 5:.1f}" x2="{xx:.1f}" y2="{yb + 5:.1f}" stroke="#333" stroke-width="1"/>')
        out.append(f'<text x="{(xa + xb) / 2:.1f}" y="{yb + (14 if near_edge > 0 else -6):.1f}" font-size="11" text-anchor="middle" fill="#222">{text}</text>')

    # North arrow and scale bar
    rot = 90 - cl.bearing_deg((dims.work_start_station_ft + dims.work_end_station_ft) / 2)
    out.append(
        f'<g transform="translate({W - 40},{H - 50}) rotate({rot:.1f})"><polygon points="0,-18 7,8 0,3 -7,8" fill="#222"/>'
        f'<text x="0" y="22" font-size="11" text-anchor="middle" font-weight="bold" transform="rotate({-rot:.1f} 0 18)">N</text></g>'
    )
    bar_ft = _nice(200 / sx)
    out.append(f'<g transform="translate({MARGIN_X},{H - 22})"><rect width="{bar_ft * sx / 2:.1f}" height="6" fill="#222"/>'
               f'<rect x="{bar_ft * sx / 2:.1f}" width="{bar_ft * sx / 2:.1f}" height="6" fill="#fff" stroke="#222"/>'
               f'<text x="0" y="-4" font-size="10">0</text><text x="{bar_ft * sx:.1f}" y="-4" font-size="10" text-anchor="end">{bar_ft:.0f} ft</text>'
               f'<text x="{bar_ft * sx + 12:.1f}" y="6" font-size="10" fill="#555">Lengths to scale; lateral widths exaggerated. Road shown straightened.</text></g>')
    out.append("</svg>")
    return "".join(out)


def _arrow(x: float, y: float, d: int) -> str:
    return f'<polygon points="{x:.1f},{y - 4:.1f} {x + 14 * d:.1f},{y:.1f} {x:.1f},{y + 4:.1f}" fill="#fff" fill-opacity="0.85"/>'


def _nice(v: float) -> float:
    exp = 10 ** math.floor(math.log10(max(v, 1)))
    for m in (1, 2, 5, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def render_timeline_svg(phases, night_phases: list[str]) -> str:
    if not phases:
        return ""
    start = min(p.start_date for p in phases)
    end = max(p.end_date for p in phases)
    days = max(1, (end - start).days + 1)
    left, width = 200, 760
    row_h = 26
    h = 40 + row_h * len(phases)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 {h}" width="100%" font-family="Arial, Helvetica, sans-serif" font-size="11">']
    for k in range(days + 1):
        if days <= 31 or k % max(1, days // 15) == 0:
            x = left + width * k / days
            out.append(f'<line x1="{x:.1f}" y1="22" x2="{x:.1f}" y2="{h - 6}" stroke="#ddd"/>')
            if k < days:
                from datetime import timedelta

                dd = start + timedelta(days=k)
                out.append(f'<text x="{x + 2:.1f}" y="16" fill="#555">{dd:%m/%d}</text>')
    for i, p in enumerate(phases):
        y = 28 + i * row_h
        x0 = left + width * (p.start_date - start).days / days
        x1 = left + width * ((p.end_date - start).days + 1) / days
        night = p.name in night_phases
        out.append(f'<text x="6" y="{y + 14}" fill="#222">{_esc(p.name)}</text>')
        out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(4, x1 - x0):.1f}" height="18" rx="3" fill="{"#1e3a5f" if night else "#f07c1b"}"/>')
        out.append(f'<text x="{x0 + 6:.1f}" y="{y + 13}" fill="#fff">{p.start_time:%H:%M}-{p.end_time:%H:%M}{" (night)" if night else ""}</text>')
    out.append("</svg>")
    return "".join(out)
