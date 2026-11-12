"""Plain-language explanation of a plan, generated from the plan data (deterministic)."""

from __future__ import annotations

from collections import Counter

from ..geo import Centerline
from ..models import DeviceType, Project, TcpPlan

DEVICE_WORDS = {
    "pole": ("pole", "poles"), "transformer": ("transformer", "transformers"), "switch": ("switch", "switches"),
    "streetlight": ("streetlight", "streetlights"), "guy_anchor": ("guy/anchor", "guys/anchors"),
    "conductor": ("conductor span", "conductor spans"), "vault": ("vault", "vaults"), "riser": ("riser", "risers"),
    "conduit": ("conduit run", "conduit runs"), "cabinet": ("cabinet", "cabinets"), None: ("facility", "facilities"),
}


def _bound(bearing: float) -> str:
    return ["northbound", "eastbound", "southbound", "westbound"][int(((bearing + 45) % 360) // 90)]


def work_summary(project: Project) -> str:
    if project.details.description:
        return project.details.description.rstrip(".")
    items = [i for i in (project.extraction.items if project.extraction else []) if i.included]
    if not items:
        return "perform electrical utility work"
    parts = []
    for action in ("construct", "remove"):
        c = Counter(i.device_type for i in items if i.action.value == action)
        if not c:
            continue
        words = []
        for dt, n in c.most_common():
            one, many = DEVICE_WORDS.get(dt, DEVICE_WORDS[None])
            words.append(f"{n} {one if n == 1 else many}")
        verb = "install" if action == "construct" else "remove"
        parts.append(f"{verb} {_join(words)}")
    return _join(parts)


def _join(xs: list[str]) -> str:
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " and " + xs[-1]


def explain(project: Project, plan: TcpPlan) -> list[str]:
    det, road, dims = project.details, project.road, plan.dimensions
    cl = Centerline.for_road(road)
    mid = (dims.work_start_station_ft + dims.work_end_station_ft) / 2
    fwd = cl.bearing_deg(mid)
    d = 1 if dims.work_end_station_ft >= dims.work_start_station_ft else -1
    bound = _bound(fwd if d == 1 else (fwd + 180) % 360)
    where = road.name or "the street"
    place = f" near {det.address}" if det.address else ""
    city = f" in {det.city}" if det.city else ""
    utility = det.utility_name or "The utility"

    paras = []
    # the side as the affected driver sees it: on a two-way road the work is always in that
    # direction's curb (right) lane or shoulder; on a one-way street it is the side chosen
    drv = det.side if road.one_way else "right"
    if plan.template == "shoulder":
        closure = f"the {bound} {drv} shoulder/parking area of {where} will be closed for {dims.work_area_ft:.0f} ft"
        flow = f"All travel lanes stay open. Cones guide traffic past the work area with a {dims.taper_ft:.0f} ft shoulder taper."
    elif plan.template == "lane_closure_multilane":
        closure = f"the {bound} {drv} lane of {where} will be closed for {dims.work_area_ft:.0f} ft"
        other = "left" if drv == "right" else "right"
        flow = (
            f"{bound.capitalize()} traffic will merge {other} using a {dims.taper_ft:.0f} ft taper, followed by a "
            f"{dims.buffer_ft:.0f} ft buffer space before the work area. Other lanes stay open."
        )
    elif plan.template == "lane_shift_twltl":
        closure = f"the {bound} lane of {where} will be closed for {dims.work_area_ft:.0f} ft"
        flow = (
            f"{bound.capitalize()} traffic will shift into the center turn lane using a {dims.taper_ft:.0f} ft shifting taper, "
            f"followed by a {dims.buffer_ft:.0f} ft buffer space; devices along the center turn lane keep it separate from opposing "
            "traffic, and left turns from the center lane are not available next to the work area. Both directions stay open."
        )
    else:
        closure = f"the {bound} lane of {where} will be closed for {dims.work_area_ft:.0f} ft"
        flow = (
            "Traffic in both directions will share the open lane, one direction at a time. "
            "Flaggers at each end will stop and release traffic."
        )
    paras.append(f"{utility} will {work_summary(project)} on {where}{place}{city}. To do the work safely, {closure}. {flow}")

    first_sign = max(
        (abs(dv.station_ft - dims.work_start_station_ft) for dv in plan.devices if dv.group == "advance_warning" and dv.station_ft is not None),
        default=0,
    )
    extra = []
    if first_sign:
        extra.append(f"Warning signs start about {first_sign:,.0f} ft ahead of the work area (posted speed {dims.speed_mph} mph).")
    if any(dv.type == DeviceType.arrow_board for dv in plan.devices):
        extra.append("An arrow board is placed at the start of the taper.")
    police = [r for r in plan.requirements if r.kind == "police" and r.required]
    if police:
        extra.append(
            "A uniformed police officer will be on site"
            + (f" ({police[0].text.split(': ', 1)[-1]})" if ": " in police[0].text else "")
            + "."
        )
    if any(z.kind == "reduced_speed" for z in plan.zones):
        rs = next(dv.label for dv in plan.devices if dv.code == "W3-5")
        extra.append(f"A work zone speed limit will be posted ({rs.split('SPEED ')[-1].replace(' AHEAD', '')} mph).")
    if plan.night:
        extra.append(
            "Part of the work takes place at night. For night work, signs have flashing warning lights, drums with steady-burn lights replace cones, "
            "and light towers illuminate the work area and flagger stations."
        )
    near_ints = [dv for dv in plan.devices if dv.group == "cross_street"]
    if near_ints:
        extra.append("Cross-street approaches within the zone also receive ROAD WORK AHEAD signs.")
    if det.pedestrian_detour:
        extra.append("The sidewalk next to the work area will be closed with SIDEWALK CLOSED barricades; pedestrians will be directed to the other side.")
    elif road.has_sidewalk:
        extra.append("The sidewalk stays open.")
    if extra:
        paras.append(" ".join(extra))
    return paras
