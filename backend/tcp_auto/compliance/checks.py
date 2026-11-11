"""Compliance checks run on a plan after generation and after every edit in the editor.

Devices are re-projected onto the centerline from their current lat/lon, so moving a device by
drag-and-drop immediately updates the measured distances.
"""

from __future__ import annotations

from ..geo import Centerline
from ..models import ComplianceIssue, DeviceType, LatLon, RoadContext, TcpPlan

TOL = 0.95  # allow 5% for hand placement


def _stations(plan: TcpPlan, cl: Centerline) -> None:
    for dv in plan.devices:
        st, off = cl.project(LatLon(lat=dv.lat, lon=dv.lon))
        dv.station_ft, dv.offset_ft = round(st, 1), round(off, 1)


def check(plan: TcpPlan, road: RoadContext) -> list[ComplianceIssue]:
    cl = Centerline.for_road(road)
    _stations(plan, cl)
    dims = plan.dimensions
    d = 1 if dims.work_end_station_ft >= dims.work_start_station_ft else -1
    out: list[ComplianceIssue] = []

    def dist_up(station: float) -> float:
        """Distance upstream of the work start (positive = upstream)."""
        return (dims.work_start_station_ft - station) * d

    # Work area length (design minimum for two large trucks)
    work_len = abs(dims.work_end_station_ft - dims.work_start_station_ft)
    if work_len < 250 * TOL:
        out.append(ComplianceIssue(severity="error", message=f"Work area is {work_len:.0f} ft; minimum is 250 ft for two large utility trucks."))

    # Taper
    taper = sorted((dv for dv in plan.devices if dv.group == "taper" and dv.type in (DeviceType.cone, DeviceType.drum)), key=lambda x: dist_up(x.station_ft))
    if len(taper) >= 2:
        length = dist_up(taper[-1].station_ft) - dist_up(taper[0].station_ft)
        if length < dims.taper_ft * TOL:
            out.append(ComplianceIssue(
                severity="error",
                message=f"Taper is {length:.0f} ft; needs at least {dims.taper_ft:.0f} ft at {dims.speed_mph} mph ({dims.taper_type}).",
                device_ids=[t.id for t in taper],
            ))
        gaps = [dist_up(b.station_ft) - dist_up(a.station_ft) for a, b in zip(taper, taper[1:])]
        worst = max(gaps) if gaps else 0
        if worst > dims.taper_spacing_ft / TOL:
            out.append(ComplianceIssue(severity="warning", message=f"Taper device gap of {worst:.0f} ft exceeds {dims.taper_spacing_ft:.0f} ft spacing.", device_ids=[t.id for t in taper]))
        buffer_measured = dist_up(taper[0].station_ft)
        if buffer_measured < dims.buffer_ft * TOL:
            out.append(ComplianceIssue(severity="warning", message=f"Buffer space is {buffer_measured:.0f} ft; recommended {dims.buffer_ft:.0f} ft at {dims.speed_mph} mph.", device_ids=[taper[0].id]))
    elif plan.template != "shoulder" or taper:
        out.append(ComplianceIssue(severity="error", message="No taper devices found."))

    # Tangent spacing
    tangent = sorted((dv for dv in plan.devices if dv.group == "tangent"), key=lambda x: -dist_up(x.station_ft))
    gaps = [abs(dist_up(a.station_ft) - dist_up(b.station_ft)) for a, b in zip(tangent, tangent[1:])]
    if gaps and max(gaps) > dims.tangent_spacing_ft / TOL:
        out.append(ComplianceIssue(severity="warning", message=f"Tangent device gap of {max(gaps):.0f} ft exceeds {dims.tangent_spacing_ft:.0f} ft spacing."))

    # Advance warning sign spacing (affected direction)
    if taper:
        taper_start = dist_up(taper[-1].station_ft)
        signs = sorted((dv for dv in plan.devices if dv.group == "advance_warning" and dv.type == DeviceType.sign and dv.code != "W16-1P"), key=lambda x: dist_up(x.station_ft))
        need = [dims.sign_spacing_ft.get(k, 0) for k in ("A", "B", "C")]
        prev = taper_start
        for i, sg in enumerate(signs[:3]):
            gap = dist_up(sg.station_ft) - prev
            if gap < need[i] * TOL:
                label = "taper" if i == 0 else f"the {signs[i - 1].code} sign"
                out.append(ComplianceIssue(
                    severity="error",
                    message=f"{sg.code} is {gap:.0f} ft from {label}; needs at least {need[i]:.0f} ft (distance {'ABC'[i]}).",
                    device_ids=[sg.id],
                ))
            prev = dist_up(sg.station_ft)

    # Required items
    has = {t: any(dv.type == t for dv in plan.devices) for t in DeviceType}
    if any(r.kind == "police" and r.required for r in plan.requirements) and not has[DeviceType.police]:
        out.append(ComplianceIssue(severity="error", message="A police officer is required but none is placed on the plan."))
    if plan.template == "two_lane_flagger":
        n = sum(1 for dv in plan.devices if dv.type == DeviceType.flagger)
        if n < 2 and not road.one_way:
            out.append(ComplianceIssue(severity="error", message=f"One-lane two-way operation needs a flagger at each end ({n} placed)."))
    if any(r.kind == "device" and "arrow" in r.text.lower() for r in plan.requirements) and not has[DeviceType.arrow_board]:
        out.append(ComplianceIssue(severity="error", message="An arrow board is required by local rules but none is placed."))
    if plan.night:
        if any(dv.type == DeviceType.cone and dv.group == "taper" for dv in plan.devices):
            out.append(ComplianceIssue(severity="warning", message="Cones in tapers at night are strongly discouraged (ADOT); use drums or vertical panels."))
        unlit = [dv.id for dv in plan.devices if dv.type == DeviceType.sign and dv.group.startswith("advance") and not dv.lights]
        if unlit:
            out.append(ComplianceIssue(severity="warning", message="Night work: advance warning signs should have flashing warning lights.", device_ids=unlit))
    return out


def device_counts(plan: TcpPlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dv in plan.devices:
        key = f"Sign {dv.code}" if dv.type == DeviceType.sign else {
            DeviceType.cone: "Cones (28 in min.)",
            DeviceType.drum: "Drums",
            DeviceType.barricade3: "Type 3 barricades",
            DeviceType.arrow_board: "Arrow boards",
            DeviceType.cms: "Changeable message boards",
            DeviceType.flagger: "Flaggers",
            DeviceType.police: "Police officers",
            DeviceType.truck: "Utility trucks",
            DeviceType.light_tower: "Light towers",
        }[dv.type]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
