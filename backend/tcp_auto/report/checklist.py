"""User checklist ("gotchas"): everything the crew/designer must handle that does NOT belong on the
plan submitted to the agency: permits and lead times, bookings, unverified rules, open review
notes, missing info, on-site reminders, and fees."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Project
from ..pipeline import timeline_for
from ..rules.engine import ResolvedRules, resolve


@dataclass
class Item:
    text: str
    cite: str = ""
    level: str = "todo"  # todo | warn | error | info
    tag: str = ""  # e.g. "confirm with agency"


@dataclass
class Section:
    title: str
    items: list[Item] = field(default_factory=list)


def _peak(rules: ResolvedRules) -> Item | None:
    rv = rules.rule("peak_hours")
    if not rv or not isinstance(rv.value, dict):
        return None
    v = rv.value
    what = "lane closures" if v.get("effect") == "no_lane_closures" else "restrictions"
    return Item(f"No {what} on weekday {'/'.join(v.get('road_class', []))} streets during {' and '.join(v.get('weekdays', []))}"
                + (f" (exceptions: {v['exceptions']})" if v.get("exceptions") else "") + ".", rv.cite, tag="" if rv.verified else "confirm with agency")


def build_checklist(project: Project) -> list[Section]:
    d, plan, road = project.details, project.plan, project.road
    rules = resolve(d)
    tl = timeline_for(project, rules)
    sections: list[Section] = []

    # 1. Before submitting
    s = Section("Before you submit")
    s.items.append(Item("Have the plan reviewed and approved by a qualified person (PE or certified TCP designer) before submitting.", level="todo"))
    for i in plan.issues:
        if i.severity in ("error", "warning"):
            s.items.append(Item(i.message, i.rule_ref or "", level="error" if i.severity == "error" else "warn"))
    if not road.speed_confirmed:
        s.items.append(Item(f"Confirm the posted speed ({road.speed_mph} mph) in the field; it sets taper, buffer, and sign spacing.", level="warn"))
    missing = [label for label, val in [("permit #", d.permit_number), ("job #", d.job_number), ("field supervisor", d.contacts.field_supervisor),
                                        ("24-hour emergency contact", d.contacts.emergency_contact), ("preparer", d.contacts.preparer)] if not val]
    if missing:
        s.items.append(Item("Fill in missing details shown on the report: " + ", ".join(missing) + ".", level="warn"))
    for r in plan.requirements:
        if r.kind == "permit":
            s.items.append(Item(r.text, r.citation, tag="" if r.verified else "confirm with agency"))
    sub = rules.rule("tcp_submittal")
    if sub and isinstance(sub.value, dict):
        v = sub.value
        if v.get("method"):
            methods = v["method"] if isinstance(v["method"], list) else [v["method"]]
            s.items.append(Item("Submit via: " + "; ".join(methods) + ".", sub.cite))
        if v.get("required_contents"):
            s.items.append(Item("The agency requires these on the plan: " + "; ".join(v["required_contents"]) + ".", sub.cite))
        if v.get("package"):
            pkg = v["package"] if isinstance(v["package"], list) else [v["package"]]
            s.items.append(Item("Submittal package: " + "; ".join(pkg) + ".", sub.cite))
    for w in rules.warnings:
        s.items.append(Item(w, level="info"))
    sections.append(s)

    # 2. Bookings & scheduling
    s = Section("Bookings & scheduling")
    police = [r for r in plan.requirements if r.kind == "police"]
    for r in police:
        if r.required:
            s.items.append(Item("Book a police officer: " + r.text, r.citation, level="todo", tag="" if r.verified else "confirm with agency"))
        else:
            s.items.append(Item("Ask the agency whether an officer is needed: " + r.text, r.citation, level="info", tag="" if r.verified else "confirm with agency"))
    for r in plan.requirements:
        if r.kind == "notice":
            s.items.append(Item(r.text, r.citation, tag="" if r.verified else "confirm with agency"))
    if (pk := _peak(rules)):
        s.items.append(pk)
    wh = rules.rule("work_hours")
    if wh and isinstance(wh.value, dict) and wh.value.get("outside_hours"):
        s.items.append(Item(f"Work outside allowed hours needs: {wh.value['outside_hours']}.", wh.cite))
    for c in tl.checklist:
        s.items.append(Item(c, rules.rule("night_work").cite if rules.rule("night_work") else ""))
    for r in plan.requirements:
        if r.kind == "personnel":
            s.items.append(Item(r.text, r.citation, tag="" if r.verified else "confirm with agency"))
    sections.append(s)

    # 3. On site
    s = Section("On site")
    s.items.append(Item("Keep a copy of the approved TCP and permit on site."))
    for r in plan.requirements:
        if r.kind in ("device", "checklist"):
            s.items.append(Item(r.text, r.citation, tag="" if r.verified else "confirm with agency"))
    nice = {"le_3in": "3 in or less", "3_to_18in": "3 to 18 in", "ge_18in": "18 in or more", "open_trench": "open trench",
            "transit_stop_relocation_max_ft_without_approval": "transit stop moved more than (ft) needs approval",
            "roadway_detour_protection": "pedestrian detour in roadway", "min_route_width_ft": "minimum route width (ft)"}
    for key, title in (("drop_off", "Pavement drop-off"), ("pedestrian", "Pedestrians")):
        rv = rules.rule(key)
        if rv and isinstance(rv.value, dict):
            for k, v in rv.value.items():
                s.items.append(Item(f"{title} – {nice.get(k, k.replace('_', ' '))}: {v}", rv.cite))
    note = rules.rule("note")
    if note and note.value:
        s.items.append(Item(str(note.value), note.cite, tag="" if note.verified else "confirm with agency"))
    sections.append(s)

    # 4. Fees & contacts
    s = Section("Fees & agency contacts")
    fees = rules.rule("fees")
    if fees and isinstance(fees.value, dict):
        for k, v in fees.value.items():
            s.items.append(Item(f"Fee – {k.replace('_', ' ')}: {v}", fees.cite, level="info"))
    contacts = rules.rule("contacts")
    if contacts and isinstance(contacts.value, dict):
        for k, v in contacts.value.items():
            s.items.append(Item(f"{k.replace('_', ' ').title()}: {v}", contacts.cite, level="info"))
    if s.items:
        sections.append(s)
    return [sec for sec in sections if sec.items]
