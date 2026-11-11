"""Draft TCP layout generator.

Everything is placed by linear referencing along the road centerline: a station (ft along the
line) and an offset (ft right of the forward direction). Templates follow MUTCD typical
applications, with Arizona practice from the ADOT TTC Design Guidelines:

- ``shoulder``                 shoulder / parking-lane work (TA-6 style)
- ``two_lane_flagger``         one lane closed on a two-lane road, flaggers (TA-10 style)
- ``lane_closure_multilane``   one lane closed where the direction has 2+ lanes (TA-30/33 style)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..geo import Centerline
from ..models import (
    ComplianceIssue,
    Device,
    DeviceType,
    LatLon,
    LayoutDimensions,
    ProjectDetails,
    Requirement,
    RoadContext,
    TcpPlan,
    Zone,
)
from ..rules.engine import Facts, ResolvedRules, evaluate
from ..timeline.schedule import TimelineResult

SHOULDER_WIDTH_FT = 8.0
SIGN_EDGE_OFFSET_FT = 6.0  # signs sit just beyond the edge of the traveled way
TRUCK_LENGTH_FT = 40.0
WORK_CLEARANCE_FT = 25.0  # each end of the work items

BUFFER_TABLE = {20: 115, 25: 155, 30: 200, 35: 250, 40: 305, 45: 360, 50: 425, 55: 495, 60: 570, 65: 645, 70: 730, 75: 820}


# ---------------------------------------------------------------------------
# Dimension rules
# ---------------------------------------------------------------------------


def merging_taper_ft(width_ft: float, speed_mph: int) -> float:
    """MUTCD: L = W*S^2/60 for S <= 40 mph, L = W*S for S >= 45 mph."""
    if speed_mph <= 40:
        return width_ft * speed_mph**2 / 60.0
    return width_ft * speed_mph


def buffer_ft(speed_mph: int, rules: ResolvedRules | None = None) -> float:
    table = BUFFER_TABLE
    if rules and isinstance(rules.get("buffer_length_ft"), dict):
        table = {int(k): float(v) for k, v in rules.get("buffer_length_ft").items()}
    keys = sorted(table)
    s = max(keys[0], min(keys[-1], int(math.ceil(speed_mph / 5.0) * 5)))
    return float(table[s])


def sign_spacing(speed_mph: int, road_class: str, rules: ResolvedRules | None = None) -> tuple[str, dict[str, float]]:
    """Advance warning sign spacing (A, B, C). The agency sets the speed category; v1 uses
    <= 30 mph urban low speed, 35-45 mph urban high speed, >= 50 mph rural, highways expressway."""
    table = {
        "urban_low_speed": {"A": 100, "B": 100, "C": 100},
        "urban_high_speed": {"A": 350, "B": 350, "C": 350},
        "rural": {"A": 500, "B": 500, "C": 500},
        "expressway": {"A": 1000, "B": 1500, "C": 2640},
    }
    if rules and isinstance(rules.get("advance_warning_sign_spacing"), dict):
        table.update(rules.get("advance_warning_sign_spacing"))
    if road_class == "highway":
        cat = "expressway"
    elif speed_mph <= 30:
        cat = "urban_low_speed"
    elif speed_mph <= 45:
        cat = "urban_high_speed"
    else:
        cat = "rural"
    return cat, {k: float(v) for k, v in table[cat].items()}


def device_spacing(speed_mph: int, rules: ResolvedRules | None = None) -> tuple[float, float]:
    """(taper spacing, tangent spacing) in ft."""
    ds = rules.get("device_spacing") if rules else None
    if isinstance(ds, dict) and "posted_ge_40mph" in ds and speed_mph >= 40:
        v = ds["posted_ge_40mph"]
        return float(v["taper_ft"]), float(v["tangent_ft"])
    return float(speed_mph), float(2 * speed_mph)


# ---------------------------------------------------------------------------
# Road geometry helpers
# ---------------------------------------------------------------------------


@dataclass
class Geometry:
    cl: Centerline
    dir: int  # +1 if the affected traffic travels forward (increasing station), else -1
    sgn: int  # +1 if the work side is right of the forward direction, -1 if left
    outer_edge: float  # signed offset of the outer edge of the traveled way on the work side
    inner_line: float  # signed offset of the lane line beside the closed lane
    opp_edge: float  # signed offset of the opposite outer edge
    lane_w: float
    lanes_affected_dir: int
    lanes_opposing: int


def _geometry(road: RoadContext, details: ProjectDetails, cl: Centerline) -> Geometry:
    w = road.lane_width_ft
    if road.one_way:
        n = road.lanes_forward + road.lanes_backward
        half = n * w / 2.0
        sgn = 1 if details.side == "right" else -1
        outer = sgn * half
        return Geometry(cl, +1, sgn, outer, outer - sgn * w, -outer, w, n, 0)
    if details.side == "right":
        outer = road.lanes_forward * w
        return Geometry(cl, +1, +1, outer, outer - w, -road.lanes_backward * w, w, road.lanes_forward, road.lanes_backward)
    outer = -road.lanes_backward * w
    return Geometry(cl, -1, -1, outer, outer + w, road.lanes_forward * w, w, road.lanes_backward, road.lanes_forward)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def choose_template(road: RoadContext, details: ProjectDetails, g: Geometry) -> str:
    if details.work_position == "shoulder":
        return "shoulder"
    if g.lanes_affected_dir >= 2:
        return "lane_closure_multilane"
    return "two_lane_flagger"


def generate(
    road: RoadContext,
    details: ProjectDetails,
    rules: ResolvedRules,
    work_center: LatLon,
    work_extent_ft: float,
    timeline: TimelineResult,
) -> TcpPlan:
    cl = Centerline.for_road(road)
    g = _geometry(road, details, cl)
    s_c, _ = cl.project(work_center)
    S = int(road.speed_mph)
    template = choose_template(road, details, g)
    issues: list = []

    if road.one_way and g.lanes_affected_dir <= 1 and template != "shoulder":
        issues.append(
            ComplianceIssue(
                severity="error",
                message="Closing the only lane of a one-way street needs a full road closure and detour plan (not generated in v1).",
            )
        )

    # --- dimensions -------------------------------------------------------------------------
    min_work = float(rules.get("min_work_area_ft", 250) or 250)
    work_len = max(min_work, work_extent_ft + 2 * WORK_CLEARANCE_FT, details.trucks * (TRUCK_LENGTH_FT + 10) + 2 * WORK_CLEARANCE_FT)
    buf = buffer_ft(S, rules)
    if template == "shoulder":
        taper_w = SHOULDER_WIDTH_FT
        taper = max(50.0, 0.33 * merging_taper_ft(taper_w, S))
        taper_type = "shoulder (0.33 L)"
    elif template == "lane_closure_multilane":
        taper_w = g.lane_w
        taper = merging_taper_ft(taper_w, S)
        taper_type = "merging (L)"
    else:
        taper_w = g.lane_w
        taper = 50.0 if S <= 30 else 100.0
        taper_type = "one-lane two-way (50-100 ft)"
    down_taper = 100.0
    cat, spacing = sign_spacing(S, road.road_class.value, rules)
    taper_sp, tangent_sp = device_spacing(S, rules)
    if template == "two_lane_flagger":
        taper_sp = 20.0  # ADOT: one-lane two-way operations
    A, B, C = spacing["A"], spacing["B"], spacing["C"]

    d = g.dir
    ws = s_c - d * work_len / 2  # work start (first point reached by affected traffic)
    we = s_c + d * work_len / 2

    def up(u: float) -> float:  # station u ft upstream of the work start
        return ws - d * u

    def dn(v: float) -> float:  # station v ft downstream of the work end
        return we + d * v

    devices: list[Device] = []

    def add(dtype: DeviceType, station: float, offset: float, *, code=None, label="", group="", direction="forward", lights=None, rule_ref=None):
        p = cl.point(station, offset)
        bearing = cl.bearing_deg(station)
        if direction == "backward":
            bearing = (bearing + 180) % 360
        devices.append(
            Device(
                type=dtype, code=code, label=label, lat=p.lat, lon=p.lon, station_ft=round(station, 1),
                offset_ft=round(offset, 1), rotation_deg=round(bearing, 1),
                direction=direction, group=group, lights=lights, rule_ref=rule_ref,
            )
        )

    affected_dir = "forward" if d == 1 else "backward"
    opposing_dir = "backward" if d == 1 else "forward"
    night = timeline.night
    chan = DeviceType.drum if night else DeviceType.cone  # ADOT: cones discouraged in tapers at night
    chan_lights = "Type C steady-burn" if night else None
    sign_lights = "Type A flashing" if night else None
    sign_off = g.outer_edge + g.sgn * SIGN_EDGE_OFFSET_FT
    opp_sign_off = g.opp_edge - g.sgn * SIGN_EDGE_OFFSET_FT

    # --- facts & requirements ----------------------------------------------------------------
    adv_lo, adv_hi = sorted((up(buf + taper + A + B + C), dn(down_taper)))  # whole TTC zone
    res_lo, res_hi = sorted((up(buf + taper), dn(down_taper)))  # taper start to downstream taper end
    signal_dist, signal_in_zone, near_ints = _intersection_facts(road, adv_lo, adv_hi, res_lo, res_hi, min(ws, we), max(ws, we))
    lane_closure = template != "shoulder"
    through_remaining = (g.lanes_affected_dir - 1) if template == "lane_closure_multilane" else (1 if template == "two_lane_flagger" else g.lanes_affected_dir)
    facts = Facts(
        road_class=road.road_class.value,
        speed_mph=S,
        lane_closure=lane_closure,
        through_lanes_remaining=through_remaining,
        school_zone=details.school_zone,
        min_signal_distance_ft=signal_dist,
        signal_in_zone=signal_in_zone,
        night=night,
        duration=timeline.duration,
        duration_days=timeline.duration_days,
        flagging=template == "two_lane_flagger",
        bike_lane_closed=road.has_bike_lane and details.side == "right" and not road.one_way,
        capacity_reduction_pct=(100.0 / g.lanes_affected_dir) if lane_closure and g.lanes_affected_dir else 0.0,
        during_peak=timeline.during_peak,
    )
    reqs: list[Requirement] = evaluate(rules, facts)
    if details.police_requested and not any(r.kind == "police" and r.required for r in reqs):
        reqs.append(Requirement(kind="police", text="Police officer requested by the project team", citation="Project details"))
    police_required = any(r.kind == "police" and r.required for r in reqs)
    device_text = " ".join(r.text.lower() for r in reqs if r.kind == "device")

    # --- work area & trucks -----------------------------------------------------------------
    if template == "shoulder":
        work_lo, work_hi = g.outer_edge, g.outer_edge + g.sgn * SHOULDER_WIDTH_FT
    else:
        work_lo, work_hi = g.inner_line, g.outer_edge
    truck_off = (work_lo + work_hi) / 2
    for i in range(details.trucks):
        st = ws + d * (WORK_CLEARANCE_FT + TRUCK_LENGTH_FT / 2 + i * (TRUCK_LENGTH_FT + 10))
        add(DeviceType.truck, st, truck_off, label=f"Utility truck {i + 1}", group="work", direction=affected_dir)

    # --- channelizing devices -----------------------------------------------------------------
    if template == "shoulder":
        taper_from, taper_to = g.outer_edge + g.sgn * SHOULDER_WIDTH_FT, g.outer_edge
        tangent_line = g.outer_edge + g.sgn * 1.0
    else:
        taper_from, taper_to = g.outer_edge, g.inner_line
        tangent_line = g.inner_line
    n_taper = max(3, int(math.ceil(taper / taper_sp)) + 1)
    for k in range(n_taper):
        t = k / (n_taper - 1)
        u = buf + taper * (1 - t)
        add(chan, up(u), taper_from + (taper_to - taper_from) * t, label="Taper", group="taper", direction=affected_dir, lights=chan_lights)
    tangent_len = buf + work_len
    n_tan = max(2, int(math.ceil(tangent_len / tangent_sp)))
    for k in range(1, n_tan + 1):
        u_from_taper_end = tangent_len * k / n_tan
        add(chan, up(buf) + d * u_from_taper_end, tangent_line, label="Tangent", group="tangent", direction=affected_dir, lights=chan_lights)
    n_down = max(3, int(math.ceil(down_taper / 20.0)) + 1)
    for k in range(1, n_down):
        t = k / (n_down - 1)
        add(chan, dn(down_taper * t), taper_to + (taper_from - taper_to) * t, label="Downstream taper", group="termination", direction=affected_dir, lights=chan_lights)

    # --- arrow board ----------------------------------------------------------------------------
    needs_arrow = template == "lane_closure_multilane" and ("arrow" in device_text or S >= 45 or road.road_class.value in ("arterial", "highway"))
    if template != "two_lane_flagger" and "arrow" in device_text:
        needs_arrow = True
    if needs_arrow:
        add(DeviceType.arrow_board, up(buf + taper), (g.outer_edge + g.inner_line) / 2 if template != "shoulder" else g.outer_edge + g.sgn * 4,
            code="Arrow board", label="Arrow board (caution/arrow)", group="taper", direction=affected_dir,
            rule_ref=next((r.citation for r in reqs if r.kind == "device" and "arrow" in r.text.lower()), None))

    # --- advance warning signs (affected direction) ---------------------------------------------
    u0 = buf + taper
    lr = "R" if g.sgn == 1 else "L"
    if template == "lane_closure_multilane":
        seq = [(A, "W4-2" + lr, "LANE ENDS"), (A + B, "W20-5" + lr, f"{'RIGHT' if lr == 'R' else 'LEFT'} LANE CLOSED AHEAD"), (A + B + C, "W20-1", "ROAD WORK AHEAD")]
    elif template == "two_lane_flagger":
        seq = [(A, "W20-7", "FLAGGER (symbol)"), (A + B, "W20-4", "ONE LANE ROAD AHEAD"), (A + B + C, "W20-1", "ROAD WORK AHEAD")]
    else:
        seq = [(A, "W21-5", "SHOULDER WORK"), (A + B, "W20-1", "ROAD WORK AHEAD")]
    for dist, code, label in seq:
        add(DeviceType.sign, up(u0 + dist), sign_off, code=code, label=label, group="advance_warning", direction=affected_dir, lights=sign_lights)

    if facts.bike_lane_closed and ("w16-1p" in device_text or template != "shoulder"):
        add(DeviceType.sign, up(u0 + 50), sign_off, code="W16-1P", label="SHARE THE ROAD", group="advance_warning",
            direction=affected_dir, rule_ref=next((r.citation for r in reqs if "w16-1p" in r.text.lower()), None))

    end_dist = 500.0 if details.road_owner == "ADOT" else down_taper + 100.0
    end_code = "G20-2AZ" if details.road_owner == "ADOT" else "G20-2"
    add(DeviceType.sign, dn(end_dist), sign_off, code=end_code, label="END ROAD WORK", group="termination", direction=affected_dir)

    # --- flaggers (two-lane) and opposing direction --------------------------------------------
    flagger_stations: list[tuple[float, float]] = []
    if template == "two_lane_flagger" or details.flaggers_requested:
        f1 = (up(u0 + 10), sign_off)
        flagger_stations.append(f1)
        add(DeviceType.flagger, *f1, label="Flagger station 1", group="flagger", direction=affected_dir)
    if not road.one_way and template == "two_lane_flagger":
        # Opposing traffic is stopped at the far end of the work area.
        u_op = buf + down_taper
        f2 = (dn(u_op), opp_sign_off)
        flagger_stations.append(f2)
        add(DeviceType.flagger, *f2, label="Flagger station 2", group="flagger", direction=opposing_dir)
        for dist, code, label in [(A, "W20-7", "FLAGGER (symbol)"), (A + B, "W20-4", "ONE LANE ROAD AHEAD"), (A + B + C, "W20-1", "ROAD WORK AHEAD")]:
            add(DeviceType.sign, dn(u_op + dist), opp_sign_off, code=code, label=label, group="advance_warning_opposing", direction=opposing_dir, lights=sign_lights)
        add(DeviceType.sign, up(u0 + 100), opp_sign_off, code=end_code, label="END ROAD WORK", group="termination", direction=opposing_dir)
    elif not road.one_way and template == "lane_closure_multilane" and g.lanes_opposing:
        add(DeviceType.sign, dn(down_taper + A + B + C), opp_sign_off, code="W20-1", label="ROAD WORK AHEAD", group="advance_warning_opposing", direction=opposing_dir, lights=sign_lights)
        add(DeviceType.sign, up(u0 + 100), opp_sign_off, code=end_code, label="END ROAD WORK", group="termination", direction=opposing_dir)

    # --- police officer ------------------------------------------------------------------------
    if police_required:
        if near_ints:
            ix = near_ints[0]
            add(DeviceType.police, ix.station_ft, 0.0, label=f"Police officer ({ix.cross_street or 'intersection'})", group="police", direction="both")
        elif flagger_stations:
            st, off = flagger_stations[0]
            add(DeviceType.police, st - d * 15, off, label="Police officer", group="police", direction=affected_dir)
        else:
            add(DeviceType.police, up(u0), sign_off, label="Police officer", group="police", direction=affected_dir)

    # --- reduced speed zone ----------------------------------------------------------------------
    reduced = None
    if details.reduced_speed_requested and S >= 30:
        sr = rules.get("speed_reduction") or {}
        drop = int((sr.get("max_mph_without_approval") or sr.get("max_mph_typical") or 10)) if isinstance(sr, dict) else 10
        reduced = S - min(10, drop)
        add(DeviceType.sign, up(u0 + A + B + C / 2), sign_off, code="W3-5", label=f"REDUCED SPEED {reduced} AHEAD", group="speed", direction=affected_dir, lights=sign_lights)
        add(DeviceType.sign, up(u0 + A / 2), sign_off, code="R2-1 + G20-5aP", label=f"WORK ZONE SPEED LIMIT {reduced}", group="speed", direction=affected_dir)
        add(DeviceType.sign, dn(down_taper + 50), sign_off, code="R2-12", label="END WORK ZONE SPEED LIMIT", group="speed", direction=affected_dir)

    # --- night lighting ----------------------------------------------------------------------------
    if night:
        n_towers = max(1, int(math.ceil(work_len / 150.0)))
        for k in range(n_towers):
            st = ws + d * work_len * (k + 0.5) / n_towers
            add(DeviceType.light_tower, st, work_hi + g.sgn * 6, label="Light tower (work area)", group="lighting", direction="both")
        for i, (st, off) in enumerate(flagger_stations):
            add(DeviceType.light_tower, st, off + (6 if off >= 0 else -6), label=f"Light tower (flagger station {i + 1})", group="lighting", direction="both")

    # --- pedestrians -----------------------------------------------------------------------------
    if details.pedestrian_detour and road.has_sidewalk:
        side_walk = g.outer_edge + g.sgn * (SHOULDER_WIDTH_FT + 8)
        for st in (up(20), dn(20)):
            add(DeviceType.barricade3, st, side_walk, code="R9-9", label="SIDEWALK CLOSED", group="pedestrian", direction="both")

    # --- cross streets -----------------------------------------------------------------------------
    for ix in near_ints:
        issues.append(
            ComplianceIssue(
                severity="warning",
                message=(
                    f"Intersection with {ix.cross_street or 'a cross street'}{' (signalized)' if ix.signalized else ''} is within the TTC zone. "
                    "Add ROAD WORK AHEAD signs on each cross-street approach (ADOT SA-8 shows 350-500 ft) and check turn movements."
                ),
            )
        )
        add(DeviceType.sign, ix.station_ft, g.opp_edge - g.sgn * 40, code="W20-1", label=f"ROAD WORK AHEAD ({ix.cross_street or 'cross street'} approach — place 350-500 ft up the cross street)", group="cross_street", direction="both")

    # --- zones -------------------------------------------------------------------------------------
    all_st = [dv.station_ft for dv in devices if dv.station_ft is not None]
    r_lo, r_hi = min(all_st) - 100, max(all_st) + 100
    if road.one_way:
        road_right = (road.lanes_forward + road.lanes_backward) * g.lane_w / 2
        road_left = -road_right
    else:
        road_left, road_right = -road.lanes_backward * g.lane_w, road.lanes_forward * g.lane_w
    road_label = f"{road.name or 'Roadway'} ({road.lanes_forward}+{road.lanes_backward} lanes{', divided' if cl.median else ''})"
    if cl.median and not road.one_way:
        # two carriageways with the median between them (tiny offsets pick up the median push-out)
        roadway = [Zone(kind="roadway", polygon=cl.strip(r_lo, r_hi, road_left, -0.001, 24), start_station_ft=r_lo, end_station_ft=r_hi, label=road_label),
                   Zone(kind="roadway", polygon=cl.strip(r_lo, r_hi, 0.001, road_right, 24), start_station_ft=r_lo, end_station_ft=r_hi, label=road_label)]
    else:
        roadway = [Zone(kind="roadway", polygon=cl.strip(r_lo, r_hi, road_left, road_right, 16), start_station_ft=r_lo, end_station_ft=r_hi, label=road_label)]
    zones = roadway + [
        Zone(kind="work_area", polygon=cl.strip(min(ws, we), max(ws, we), work_lo, work_hi), start_station_ft=min(ws, we), end_station_ft=max(ws, we), label=f"Work area {work_len:.0f} ft"),
        Zone(kind="buffer", polygon=cl.strip(min(ws, up(buf)), max(ws, up(buf)), work_lo, work_hi, 4), start_station_ft=min(ws, up(buf)), end_station_ft=max(ws, up(buf)), label=f"Buffer {buf:.0f} ft"),
        Zone(kind="taper", polygon=[cl.point(up(buf + taper), taper_from), cl.point(up(buf), taper_to), cl.point(up(buf), taper_from)], start_station_ft=min(up(buf), up(buf + taper)), end_station_ft=max(up(buf), up(buf + taper)), label=f"Taper {taper:.0f} ft"),
    ]
    if reduced:
        a, b = up(u0 + A / 2), dn(down_taper + 50)
        zones.append(Zone(kind="reduced_speed", polygon=cl.strip(min(a, b), max(a, b), g.opp_edge, g.outer_edge, 10), start_station_ft=min(a, b), end_station_ft=max(a, b), label=f"Work zone speed limit {reduced} mph"))

    dims = LayoutDimensions(
        speed_mph=S, work_area_ft=round(work_len), buffer_ft=buf, taper_ft=round(taper), taper_type=taper_type,
        downstream_taper_ft=down_taper, sign_spacing_ft=spacing,
        taper_spacing_ft=taper_sp, tangent_spacing_ft=tangent_sp, template=template,
        work_start_station_ft=round(ws, 1), work_end_station_ft=round(we, 1),
    )
    plan = TcpPlan(template=template, devices=devices, zones=zones, dimensions=dims, requirements=reqs, issues=issues, night=night)
    plan.requirements.extend(_static_requirements(rules, template, road, details))
    return plan


def _intersection_facts(road: RoadContext, zone_lo, zone_hi, restricted_lo, restricted_hi, work_lo, work_hi):
    """Intersections in the TTC zone, distance from the work area to the nearest signal, and whether
    a signal lies inside the restricted section (taper start to downstream taper end)."""
    signal_dist = None
    signal_in_zone = False
    near = []
    for ix in road.intersections:
        if zone_lo <= ix.station_ft <= zone_hi:
            near.append(ix)
        if ix.signalized:
            dist = 0.0 if work_lo <= ix.station_ft <= work_hi else min(abs(ix.station_ft - work_lo), abs(ix.station_ft - work_hi))
            signal_dist = dist if signal_dist is None else min(signal_dist, dist)
            if restricted_lo <= ix.station_ft <= restricted_hi:
                signal_in_zone = True
    near.sort(key=lambda i: (not i.signalized, abs(i.station_ft - (work_lo + work_hi) / 2)))
    return signal_dist, signal_in_zone, near


def _static_requirements(rules: ResolvedRules, template: str, road: RoadContext, details: ProjectDetails) -> list[Requirement]:
    out: list[Requirement] = []
    sub = rules.rule("tcp_submittal")
    if sub and isinstance(sub.value, dict):
        v = sub.value
        if v.get("lead_time"):
            out.append(Requirement(kind="permit", text=f"Submit the TCP at least {v['lead_time']} before work.", verified=sub.verified, citation=sub.cite))
        if v.get("prerequisite"):
            out.append(Requirement(kind="permit", text=f"Prerequisite: {v['prerequisite']}.", verified=sub.verified, citation=sub.cite))
        if v.get("preparer"):
            out.append(Requirement(kind="permit", text=f"TCP prepared by: {v['preparer']}.", verified=sub.verified, citation=sub.cite))
    pr = rules.rule("police_request")
    if pr and isinstance(pr.value, dict):
        bits = []
        if pr.value.get("lead_time_business_days"):
            bits.append(f"{pr.value['lead_time_business_days']} business days' notice")
        if pr.value.get("lead_time_hours"):
            bits.append(f"{pr.value['lead_time_hours']} hours' notice")
        if pr.value.get("phone"):
            bits.append(f"call {pr.value['phone']}")
        if bits:
            out.append(Requirement(kind="notice", text="If an officer is needed: " + ", ".join(bits) + ".", verified=pr.verified, citation=pr.cite))
    if template == "two_lane_flagger":
        fl = rules.rule("flagging")
        if fl and isinstance(fl.value, dict):
            out.append(Requirement(kind="personnel", text="Flaggers: " + " or ".join(fl.value.get("allowed", [])) + ".", verified=fl.verified, citation=fl.cite))
        else:
            out.append(Requirement(kind="personnel", text="Trained/certified flaggers at each end of the one-lane section.", citation="MUTCD Part 6 (flagger control)"))
    sz = rules.rule("school_zone")
    if details.school_zone and sz and isinstance(sz.value, dict) and sz.value.get("school_crosswalks"):
        out.append(Requirement(kind="checklist", text=f"School zone: crosswalks {sz.value['school_crosswalks']}.", verified=sz.verified, citation=sz.cite))
    return out
