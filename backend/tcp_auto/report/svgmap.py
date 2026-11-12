"""Plan-view drawing of a TCP as SVG, for the report.

The road is drawn straightened along its centerline (station on the x axis) with lateral distances
exaggerated so lanes and devices are readable on a page. A north arrow shows true orientation.
This works with no map-tile access; the interactive editor shows the same layout on an OSM map.
"""

from __future__ import annotations

import html
import math

from ..geo import Centerline, center_lane_width
from ..models import DeviceType, LatLon, ProjectDetails, RoadContext, TcpPlan

W, H = 1000, 370
MARGIN_X = 40
ROAD_Y = 182  # screen y of the centerline
HALO = ' stroke="#f5f8fb" stroke-width="3" paint-order="stroke" stroke-linejoin="round"'  # keeps labels readable over pavement


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def render_plan_svg(plan: TcpPlan, road: RoadContext, details: ProjectDetails) -> str:
    cl = Centerline.for_road(road)
    raw: dict[str, tuple[float, float]] = {}  # unrounded, so devices on a center-lane edge keep their side
    for dv in plan.devices:
        raw[dv.id] = cl.project(LatLon(lat=dv.lat, lon=dv.lon))
        dv.station_ft, dv.offset_ft = (round(v, 1) for v in raw[dv.id])
    stations = [dv.station_ft for dv in plan.devices] + [plan.dimensions.work_start_station_ft, plan.dimensions.work_end_station_ft]
    s_min, s_max = min(stations) - 60, max(stations) + 60
    sx = (W - 2 * MARGIN_X) / max(1.0, s_max - s_min)

    w = road.lane_width_ft
    if road.one_way:
        n = road.lanes_forward + road.lanes_backward
        left_edge, right_edge = -n * w / 2, n * w / 2
    else:
        left_edge, right_edge = -road.lanes_backward * w, road.lanes_forward * w
    half_c = center_lane_width(road) / 2  # center turn lane: offsets are measured from its edges
    road_w = right_edge - left_edge + 2 * half_c
    sy = 130.0 / max(road_w, 24.0)  # lateral exaggeration: road band ~130 px

    def X(st: float) -> float:
        return MARGIN_X + (st - s_min) * sx

    def Y(off: float) -> float:
        return ROAD_Y + (off + math.copysign(half_c, off) if off else off) * sy

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" font-family="Arial, Helvetica, sans-serif">',
        "<defs>"
        '<pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="8" height="8" fill="#fde3c4"/><line x1="0" y1="0" x2="0" y2="8" stroke="#f07c1b" stroke-width="3"/></pattern>'
        "</defs>",
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#f5f8fb"/>',
    ]

    # Sidewalk/shoulder strips and road
    out.append(f'<rect x="{MARGIN_X - 20}" y="{Y(left_edge) - 26:.1f}" width="{W - 2 * MARGIN_X + 40}" height="{road_w * sy + 52:.1f}" fill="#e3e8ee"/>')
    out.append(f'<rect x="{MARGIN_X - 20}" y="{Y(left_edge):.1f}" width="{W - 2 * MARGIN_X + 40}" height="{road_w * sy:.1f}" fill="#6b6f74"/>')
    lanes_total = int(round((right_edge - left_edge) / w))
    x0, x1 = MARGIN_X - 20, W - MARGIN_X + 20
    for k in range(1, lanes_total):
        off = left_edge + k * w
        if not road.one_way and abs(off) < 0.1 and half_c:
            # two-way left-turn lane: solid outer + dashed inner yellow lines each side, and turn arrows
            for sgn in (-1, 1):
                yo, yi = ROAD_Y + sgn * (half_c * sy - 2), ROAD_Y + sgn * (half_c * sy - 6)
                out.append(f'<line x1="{x0}" y1="{yo:.1f}" x2="{x1}" y2="{yo:.1f}" stroke="#f2c230" stroke-width="2"/>')
                out.append(f'<line x1="{x0}" y1="{yi:.1f}" x2="{x1}" y2="{yi:.1f}" stroke="#f2c230" stroke-width="2" stroke-dasharray="14 10"/>')
            for xa in range(int(x0) + 170, int(x1) - 60, 260):
                out.append(_turn_arrows(xa, ROAD_Y))
            out.append(f'<text x="{x0 + 8}" y="{ROAD_Y + 3.5:.1f}" font-size="9" fill="#e6e8eb">CENTER TURN LANE</text>')
        elif not road.one_way and abs(off) < 0.1:
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(0) - 2:.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(0) - 2:.1f}" stroke="#f2c230" stroke-width="2"/>')
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(0) + 2:.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(0) + 2:.1f}" stroke="#f2c230" stroke-width="2"/>')
        else:
            out.append(f'<line x1="{MARGIN_X - 20}" y1="{Y(off):.1f}" x2="{W - MARGIN_X + 20}" y2="{Y(off):.1f}" stroke="#fff" stroke-width="1.5" stroke-dasharray="14 12"/>')

    # Cross streets, drawn over the main road so the crossing reads as an intersection
    top, bot = Y(left_edge), Y(right_edge)
    for ix in road.intersections:
        if s_min - 40 <= ix.station_ft <= s_max + 40:
            out.append(_intersection(X(ix.station_ft), max(40.0, 64 * sx), top, bot, ix.cross_street, ix.signalized))

    # Direction arrows
    if not road.one_way:
        out.append(_arrow(MARGIN_X + 10, Y(right_edge - w / 2), 1))
        out.append(_arrow(W - MARGIN_X - 10, Y(left_edge + w / 2), -1))
    else:
        out.append(_arrow(MARGIN_X + 10, Y(0), 1))
    if road.name:
        out.append(f'<text x="{W - MARGIN_X - 6}" y="{Y(right_edge) + 18:.1f}" font-size="13" font-weight="bold" fill="#333" text-anchor="end"{HALO}>{_esc(road.name)}</text>')

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
        x, y = X(raw[dv.id][0]), Y(raw[dv.id][1])
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
            out.append(f'<text x="{x:.1f}" y="{ly:.1f}" font-size="10" text-anchor="middle" fill="#222" font-weight="bold"{HALO}>{_esc(dv.code or "")}</text>')

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
        out.append(f'<text x="{(xa + xb) / 2:.1f}" y="{yb + (14 if near_edge > 0 else -6):.1f}" font-size="11" text-anchor="middle" fill="#222"{HALO}>{text}</text>')

    # Cross-street names last, so nothing covers them
    for ix in road.intersections:
        if s_min - 40 <= ix.station_ft <= s_max + 40:
            out.append(_intersection_label(X(ix.station_ft), max(40.0, 64 * sx), ix.cross_street, ix.signalized))

    school_y = 46 if yb > ROAD_Y else 36  # keep clear of the dimension callouts when they are above the road
    # School: marker at the school's station (or at the map edge, pointing toward it)
    sch = details.nearby_school
    if sch and sch.lat is not None and (details.school_zone or sch.distance_ft <= 1500):
        st, off = cl.project(LatLon(lat=sch.lat, lon=sch.lon))
        fwd = cl.bearing_deg(min(max(st, 0), cl.length))
        side = ["north", "east", "south", "west"][int(((fwd + (90 if off > 0 else -90)) % 360 + 45) % 360 // 90)]
        xs = X(min(max(st, s_min), s_max))
        edge = "" if s_min <= st <= s_max else (" (beyond map ←)" if st < s_min else " (beyond map →)")
        out.append(_school_marker(min(max(xs, 16), W - 16), school_y, f"{sch.name}, {side} side, ~{sch.distance_ft:,} ft{edge}", details.school_zone))
    elif details.school_zone:
        out.append(_school_marker(MARGIN_X + 10, school_y, "location not mapped", True))

    # North arrow and scale bar
    rot = 90 - cl.bearing_deg((dims.work_start_station_ft + dims.work_end_station_ft) / 2)
    out.append(
        f'<g transform="translate({W - 40},{H - 50}) rotate({rot:.1f})"><polygon points="0,-18 7,8 0,3 -7,8" fill="#222"/>'
        f'<text x="0" y="22" font-size="11" text-anchor="middle" font-weight="bold" transform="rotate({-rot:.1f} 0 18)">N</text></g>'
    )
    bar_ft = _nice(200 / sx)
    out.append(f'<rect x="{MARGIN_X - 6}" y="{H - 38}" width="{bar_ft * sx + 360:.1f}" height="28" rx="3" fill="#f5f8fb" fill-opacity="0.92"/>')
    out.append(f'<g transform="translate({MARGIN_X},{H - 22})"><rect width="{bar_ft * sx / 2:.1f}" height="6" fill="#222"/>'
               f'<rect x="{bar_ft * sx / 2:.1f}" width="{bar_ft * sx / 2:.1f}" height="6" fill="#fff" stroke="#222"/>'
               f'<text x="0" y="-4" font-size="10">0</text><text x="{bar_ft * sx:.1f}" y="-4" font-size="10" text-anchor="end">{bar_ft:.0f} ft</text>'
               f'<text x="{bar_ft * sx + 12:.1f}" y="6" font-size="10" fill="#555">Lengths to scale; lateral widths exaggerated. Road shown straightened.</text></g>')
    out.append("</svg>")
    return "".join(out)


def _intersection(x: float, width: float, top: float, bot: float, name: str, signalized: bool) -> str:
    """A cross street at screen x crossing the main road band (top..bot): asphalt, crosswalks, stop
    bars, center line, signal heads and a name tag."""
    h = width / 2
    g = [f'<g class="cross-street">',
         f'<rect x="{x - h:.1f}" y="0" width="{width:.1f}" height="{H - 34}" fill="#6b6f74"/>',
         f'<rect x="{x - h - 3:.1f}" y="0" width="3" height="{H - 34}" fill="#c4ccd6"/>',
         f'<rect x="{x + h:.1f}" y="0" width="3" height="{H - 34}" fill="#c4ccd6"/>']
    # cross street's center line, outside the main road
    for y0, y1 in ((0, top - 14), (bot + 14, H - 34)):
        if y1 > y0:
            g.append(f'<line x1="{x - 1.5:.1f}" y1="{y0}" x2="{x - 1.5:.1f}" y2="{y1:.1f}" stroke="#f2c230" stroke-width="1.5"/>'
                     f'<line x1="{x + 1.5:.1f}" y1="{y0}" x2="{x + 1.5:.1f}" y2="{y1:.1f}" stroke="#f2c230" stroke-width="1.5"/>')
    # crosswalks across the cross street (just outside the main road) and across the main road (beside the box)
    for yc in (top - 8, bot + 8):
        g.append(f'<line x1="{x - h + 2:.1f}" y1="{yc:.1f}" x2="{x + h - 2:.1f}" y2="{yc:.1f}" stroke="#fff" stroke-width="9" stroke-dasharray="3 3"/>')
    for xc in (x - h - 9, x + h + 9):
        g.append(f'<line x1="{xc:.1f}" y1="{top + 2:.1f}" x2="{xc:.1f}" y2="{bot - 2:.1f}" stroke="#fff" stroke-width="9" stroke-dasharray="3 3"/>')
    # stop bars on the main road approaches (right-hand traffic: lower half eastbound, upper half westbound)
    mid = (top + bot) / 2
    g.append(f'<line x1="{x - h - 17:.1f}" y1="{mid + 3:.1f}" x2="{x - h - 17:.1f}" y2="{bot - 2:.1f}" stroke="#fff" stroke-width="3"/>')
    g.append(f'<line x1="{x + h + 17:.1f}" y1="{top + 2:.1f}" x2="{x + h + 17:.1f}" y2="{mid - 3:.1f}" stroke="#fff" stroke-width="3"/>')
    if signalized:
        for sx_, sy_ in ((x - h - 6, top - 22), (x + h + 6, bot + 22)):
            g.append(f'<rect x="{sx_ - 4:.1f}" y="{sy_ - 10:.1f}" width="8" height="20" rx="2" fill="#1f2328"/>'
                     f'<circle cx="{sx_:.1f}" cy="{sy_ - 6:.1f}" r="2.2" fill="#e5484d"/>'
                     f'<circle cx="{sx_:.1f}" cy="{sy_:.1f}" r="2.2" fill="#f5c518"/>'
                     f'<circle cx="{sx_:.1f}" cy="{sy_ + 6:.1f}" r="2.2" fill="#30a46c"/>')
    g.append("</g>")
    return "".join(g)


def _intersection_label(x: float, width: float, name: str, signalized: bool) -> str:
    """Name tag beside the cross street at the top (beside, so signs placed on the street stay visible)."""
    label = _esc(name or "Cross street") + (" \u00b7 signal" if signalized else "")
    tw = 6.4 * len(name or "Cross street") + (44 if signalized else 0) + 16
    lx = x + width / 2 + 8  # right of the street, or left of it near the right edge
    if lx + tw > W - 4:
        lx = x - width / 2 - 8 - tw
    lx = max(4.0, lx)
    return (f'<rect x="{lx:.1f}" y="6" width="{tw:.1f}" height="20" rx="10" fill="#1a365d"/>'
            f'<text x="{lx + tw / 2:.1f}" y="20" font-size="11.5" font-weight="bold" fill="#fff" text-anchor="middle">{label}</text>')


def _turn_arrows(x: float, y: float) -> str:
    """Opposing left-turn arrow pair painted in a two-way left-turn lane."""
    return (f'<g fill="none" stroke="#fff" stroke-width="1.6" opacity="0.9">'
            f'<path d="M{x - 18:.1f},{y + 3:.1f} h12 v-6 m-3,3 l3,-3 l3,3"/>'
            f'<path d="M{x + 18:.1f},{y - 3:.1f} h-12 v6 m3,-3 l-3,3 l-3,-3"/></g>')


def _school_marker(x: float, y: float, text: str, zone: bool) -> str:
    """School sign shape (pentagon, fluorescent yellow-green) with a label."""
    pts = f"{x:.1f},{y - 11:.1f} {x + 9:.1f},{y - 3:.1f} {x + 9:.1f},{y + 9:.1f} {x - 9:.1f},{y + 9:.1f} {x - 9:.1f},{y - 3:.1f}"
    label = ("SCHOOL ZONE · " if zone else "School · ") + _esc(text)
    tw = 6.1 * len(("SCHOOL ZONE · " if zone else "School · ") + text) + 14
    lx = min(max(x + 14, 4), W - tw - 4)
    return (f'<polygon points="{pts}" fill="#c6e03a" stroke="#1f2328" stroke-width="1.2"/>'
            f'<rect x="{lx:.1f}" y="{y - 9:.1f}" width="{tw:.1f}" height="18" rx="9" fill="#ffffff" stroke="{"#5b7f00" if zone else "#9aa4b2"}" stroke-width="1.2"/>'
            f'<text x="{lx + 7:.1f}" y="{y + 4:.1f}" font-size="10.5" font-weight="bold" fill="#2c3a00">{label}</text>')


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
    # compact: sized for a one-third-page column
    left, width = 112, 340
    row_h = 26
    h = 40 + row_h * len(phases)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 460 {h}" width="100%" font-family="Arial, Helvetica, sans-serif" font-size="11">']
    for k in range(days + 1):
        if k % max(1, math.ceil(days / 7)) == 0:  # about 7 date labels fit the column
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
        name = p.name if len(p.name) <= 17 else p.name[:16] + "…"
        out.append(f'<text x="4" y="{y + 14}" fill="#222">{_esc(name)}</text>')
        out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(4, x1 - x0):.1f}" height="18" rx="3" fill="{"#1e3a5f" if night else "#f07c1b"}"/>')
        out.append(f'<text x="{x0 + 6:.1f}" y="{y + 13}" fill="#fff">{p.start_time:%H:%M}-{p.end_time:%H:%M}{" (night)" if night else ""}</text>')
    out.append("</svg>")
    return "".join(out)
