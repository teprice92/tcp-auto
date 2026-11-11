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
from .narrative import explain
from .svgmap import render_plan_svg, render_timeline_svg

TEMPLATES = Path(__file__).with_name("templates")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEMPLATE_LABELS = {
    "shoulder": "Shoulder work (MUTCD TA-6 style)",
    "two_lane_flagger": "Lane closure, two-lane road, flaggers (MUTCD TA-10 style)",
    "lane_closure_multilane": "Lane closure, multi-lane road (MUTCD TA-30/33 style)",
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
    issues = [i for i in plan.issues if i.severity != "info"] + [i for i in plan.issues if i.severity == "info"]
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
        top_errors=[i for i in plan.issues if i.severity == "error"][:3],
        requirements=[r for r in plan.requirements if not (r.kind == "police" and r.required)],
        checklist=tl.checklist,
        issues=issues,
        counts=device_counts(plan),
        rules_chain=[f"{l} ({rules.statuses.get(l, '')})" for l in rules.chain],
        template_label=TEMPLATE_LABELS.get(plan.template, plan.template),
        owner_label=OWNER_LABELS.get(d.road_owner, d.road_owner),
        today=date.today().strftime("%b %d, %Y"),
        version=__version__,
        logo=LOGO_SVG,
    )


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        exe = os.environ.get("TCP_CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))), None)
        if not exe:
            raise
        return p.chromium.launch(executable_path=exe, args=["--no-sandbox"])


def html_to_pdf(html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="Letter", landscape=True, print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def render_pdf(project: Project) -> bytes:
    return html_to_pdf(render_html(project))
