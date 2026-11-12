"""Build the report HTML and print it to PDF."""

from __future__ import annotations

import glob
import os
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import __version__
from ..compliance.checks import device_counts
from ..models import Project
from ..pipeline import timeline_for
from ..rules.engine import resolve
from ..layout.generator import lane_config
from .narrative import explain
from .pdf import html_to_pdf  # noqa: F401  (re-exported)
from .svgmap import render_plan_svg, render_timeline_svg

TEMPLATES = Path(__file__).with_name("templates")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEMPLATE_LABELS = {
    "shoulder": "Shoulder work (MUTCD TA-6 style)",
    "two_lane_flagger": "Lane closure, two-lane road, flaggers (MUTCD TA-10 style)",
    "lane_closure_multilane": "Lane closure, multi-lane road (MUTCD TA-30/33 style)",
    "lane_shift_twltl": "Lane closure with shift into the center turn lane (MUTCD 6C shifting taper)",
}
OWNER_LABELS = {"city": "City/Town", "county": "County", "ADOT": "ADOT (state highway)", "tribal": "Tribal", "unknown": "Unknown"}

LOGO_SVG = (TEMPLATES / "logo.svg").read_text(encoding="utf-8")

_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
_env.filters["dayname"] = lambda i: DAYS[int(i)]


def render_html(project: Project) -> str:
    if not project.plan or not project.road:
        raise ValueError("Generate a plan before building the report.")
    plan, d = project.plan, project.details
    rules = resolve(d)
    tl = timeline_for(project, rules)
    return _env.get_template("report.html").render(
        d=d,
        road=project.road,
        plan=plan,
        dims=plan.dimensions,
        map_svg=render_plan_svg(plan, project.road, d),
        timeline_svg=render_timeline_svg(d.phases, tl.night_phases),
        explanation=explain(project, plan),
        phases=d.phases,
        night_phases=tl.night_phases,
        sun=tl.sun,
        police_required=[r for r in plan.requirements if r.kind == "police" and r.required],
        provisions=provisions(project),
        standards=standards(rules),
        counts=device_counts(plan),
        site=site_conditions(project),
        lane_text=lane_config(project.road),
        template_label=TEMPLATE_LABELS.get(plan.template, plan.template),
        owner_label=OWNER_LABELS.get(d.road_owner, d.road_owner),
        today=date.today().strftime("%b %d, %Y"),
        version=__version__,
        logo=LOGO_SVG,
    )


def school_text(d) -> str:
    """School zone status in plain words, saying how it was determined."""
    sch = d.nearby_school
    where = f"{sch.name}, about {sch.distance_ft:,} ft away" if sch else ""
    if d.school_zone:
        return f"Yes – {where}" if sch else "Yes (per preparer)"
    if sch:
        return f"No – nearest school is {where} (map check)"
    if d.school_checked:
        return "No – no school found within about 800 ft (map check)"
    return "No (per preparer; not map-checked)"


def site_conditions(project: Project) -> list[tuple[str, str]]:
    """Facts about the site a reviewer checks first: roadway, speed, intersections, school zone."""
    d, road, plan = project.details, project.road, project.plan
    road_desc = f"{road.road_class.value.capitalize()} – {lane_config(road)}, {road.lane_width_ft:.0f} ft lanes"
    med = max((m.width_ft for m in road.median), default=0)
    if med > 0:
        road_desc += f"; median up to {med:.0f} ft"
    rows = [("Roadway", road_desc),
            ("Posted speed", f"{road.speed_mph} mph" + ("" if road.speed_confirmed else " (from map data – confirm in the field)"))]
    st = [dv.station_ft for dv in plan.devices if dv.station_ft is not None]
    if st:
        lo, hi = min(st), max(st)
        ints = [i for i in road.intersections if lo <= i.station_ft <= hi]
        rows.append(("Intersections in zone", ", ".join(f"{i.cross_street or 'unnamed'}{' (signal)' if i.signalized else ''}" for i in ints) or "None"))
    rows.append(("School zone", school_text(d)))
    side = "closed (detour to the other side)" if d.pedestrian_detour else ("open" if road.has_sidewalk else "none")
    rows.append(("Sidewalk / bike lane", f"Sidewalk {side}" + ("; bike lane present" if road.has_bike_lane else "")))
    return rows


def provisions(project: Project) -> list[str]:
    """Plain statements of what the plan provides (for the agency)."""
    plan, d, road = project.plan, project.details, project.road
    dims = plan.dimensions
    types = {dv.type.value for dv in plan.devices}
    out = [
        f"Work area of {dims.work_area_ft:.0f} ft with a {dims.buffer_ft:.0f} ft buffer and a {dims.taper_ft:.0f} ft {dims.taper_type.split(' (')[0]} taper.",
        f"Advance warning signs at {dims.sign_spacing_ft['A']:.0f}/{dims.sign_spacing_ft['B']:.0f}/{dims.sign_spacing_ft['C']:.0f} ft spacing (posted speed {dims.speed_mph} mph).",
        f"Channelizing devices at {dims.taper_spacing_ft:.0f} ft in tapers and {dims.tangent_spacing_ft:.0f} ft along tangents.",
    ]
    if "flagger" in types:
        out.append(f"{sum(dv.type.value == 'flagger' for dv in plan.devices)} flagger station(s) controlling alternating one-way traffic.")
    if "police" in types:
        out.append("Uniformed police officer on site.")
    if "arrow_board" in types:
        out.append("Arrow board at the start of the taper.")
    if any(z.kind == "reduced_speed" for z in plan.zones):
        out.append("Work zone speed limit posted (reduction of no more than 10 mph).")
    if plan.night:
        out.append("Night work: flashing lights on signs, steady-burn lights on drums, light towers at the work area and flagger stations.")
    if d.pedestrian_detour:
        out.append("Sidewalk closed next to the work area with SIDEWALK CLOSED barricades; pedestrians use the other side.")
    elif road.has_sidewalk:
        out.append("Sidewalk remains open.")
    if road.intersections and any(dv.group == "cross_street" for dv in plan.devices):
        out.append("ROAD WORK AHEAD signs on cross-street approaches within the zone.")
    return out


def standards(rules) -> list[str]:
    from ..rules.engine import RULES_DIR, _load_file

    out = []
    for layer in rules.chain:
        try:
            name = (_load_file(layer, str(RULES_DIR)).get("jurisdiction") or {}).get("name") or layer
        except FileNotFoundError:
            name = layer
        out.append(name.replace(" (reference layer)", ""))
    return out


def render_checklist_html(project: Project) -> str:
    from .checklist import build_checklist

    if not project.plan or not project.road:
        raise ValueError("Generate a plan before building the checklist.")
    return _env.get_template("checklist.html").render(
        d=project.details, road=project.road, sections=build_checklist(project), logo=LOGO_SVG,
        today=date.today().strftime("%b %d, %Y"), version=__version__,
    )


def render_checklist_pdf(project: Project) -> bytes:
    return html_to_pdf(render_checklist_html(project), landscape=False)


def render_pdf(project: Project) -> bytes:
    return html_to_pdf(render_html(project))
