"""Rule schema: which rule keys the app understands, and validation/normalization of proposed values.

Proposals (from the AI assistant or typed by hand) go through ``check_change`` before review, so
the reviewer sees exactly what will be written and whether the planner will actually use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

ROAD_CLASSES = ["local", "collector", "arterial", "highway"]

# Conditions understood by engine.match(); anything else never matches.
CONDITIONS: dict[str, str] = {
    "school_zone": "true when the job is in a school zone",
    "during": "school_hours | work_hours | peak_hours",
    "within_ft_of_signalized_intersection": "number of feet",
    "signalized_intersection": "true when a signal is inside the closed section",
    "through_lanes_remaining": "max through lanes left open (number)",
    "road_class": f"one or a list of {ROAD_CLASSES}",
    "lane_closure": "true/false",
    "duration": "long_term | intermediate_term | short_term | short_duration",
    "duration_days_gt": "number of days",
    "capacity_reduction_pct_gte": "percent of lanes closed in one direction",
    "bike_lane_closed": "true/false",
    "installing_devices": "true",
    "city_review": "true (advisory: agency may require at review)",
    "indicated_on_accepted_tcp": "true (advisory)",
    "per_section": "section number (advisory)",
}

_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*m?\.?\s*$", re.I)


def norm_time(t: str) -> str:
    """'7:00 a.m.' -> '07:00', '3:30 pm' -> '15:30', '1530' -> '15:30'."""
    t = str(t).strip().lower().replace("noon", "12:00 pm").replace("midnight", "12:00 am")
    if re.fullmatch(r"\d{4}", t):
        return f"{t[:2]}:{t[2:]}"
    m = _TIME.match(t)
    if not m:
        raise ValueError(f"can't read time '{t}'")
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "p" and h < 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mnt < 60):
        raise ValueError(f"bad time '{t}'")
    return f"{h:02d}:{mnt:02d}"


def norm_window(w: str) -> str:
    parts = re.split(r"\s*(?:-|–|—|to)\s*", str(w).strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"time window '{w}' should look like 07:00-08:30")
    return f"{norm_time(parts[0])}-{norm_time(parts[1])}"


@dataclass
class Result:
    value: Any
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _road_classes(v, r: Result) -> list[str]:
    vals = v if isinstance(v, list) else [v]
    out = []
    for x in vals:
        x = str(x).strip().lower()
        x = {"arterials": "arterial", "collectors": "collector", "major arterial": "arterial", "minor arterial": "arterial", "residential": "local", "freeway": "highway"}.get(x, x)
        if x not in ROAD_CLASSES:
            r.errors.append(f"road class '{x}' must be one of {ROAD_CLASSES}")
        out.append(x)
    return out


def _when(when: Any, r: Result) -> dict:
    if not isinstance(when, dict) or not when:
        r.errors.append("'when' must be an object of conditions, e.g. {\"school_zone\": true}")
        return {}
    out = {}
    for k, v in when.items():
        if k not in CONDITIONS:
            r.warnings.append(f"condition '{k}' isn't understood by the planner yet, so this trigger will never fire. Known: {', '.join(CONDITIONS)}")
        if k == "road_class":
            v = _road_classes(v, r)
        out[k] = v
    return out


def _peak_hours(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("peak_hours must be an object")
        return v
    out = dict(v)
    out["road_class"] = _road_classes(v.get("road_class", []), r)
    try:
        out["weekdays"] = [norm_window(w) for w in v.get("weekdays", [])]
    except ValueError as e:
        r.errors.append(str(e))
    if not out.get("weekdays"):
        r.errors.append("peak_hours needs at least one weekday window")
    if out.get("effect", "no_restrictions") not in ("no_restrictions", "no_lane_closures"):
        r.errors.append("effect must be no_restrictions or no_lane_closures")
    out.setdefault("effect", "no_restrictions")
    return out


def _police_item(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("police trigger must be an object with 'when' and 'role'")
        return v
    out = dict(v)
    out["when"] = _when(v.get("when"), r)
    if not v.get("role"):
        out["role"] = "uniformed off-duty police officer"
        r.warnings.append("no role given; using 'uniformed off-duty police officer'")
    return out


def _device_item(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("device requirement must be an object with 'when' and 'devices'")
        return v
    out = dict(v)
    out["when"] = _when(v.get("when"), r)
    devs = v.get("devices") or []
    out["devices"] = devs if isinstance(devs, list) else [str(devs)]
    if not out["devices"]:
        r.errors.append("'devices' must list at least one device")
    return out


def _personnel_item(v, r: Result):
    if not isinstance(v, dict) or not v.get("personnel"):
        r.errors.append("personnel requirement needs 'when' and 'personnel'")
        return v
    out = dict(v)
    out["when"] = _when(v.get("when"), r)
    return out


def _night_work(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("night_work must be an object")
        return v
    out = dict(v)
    if v.get("definition"):
        try:
            out["definition"] = norm_window(v["definition"])
        except ValueError as e:
            r.errors.append(str(e))
    return out


def _work_hours(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("work_hours must be an object")
        return v
    out = dict(v)
    try:
        for k in ("commercial_industrial", "weekends_holidays"):
            if v.get(k):
                out[k] = norm_window(v[k])
        if isinstance(v.get("residential"), dict):
            out["residential"] = {season: norm_window(w) for season, w in v["residential"].items()}
            for season in out["residential"]:
                if not re.fullmatch(r"\d{2}-\d{2}\.\.\d{2}-\d{2}", season):
                    r.errors.append(f"season '{season}' should look like 04-15..10-15")
    except ValueError as e:
        r.errors.append(str(e))
    return out


def _police_request(v, r: Result):
    if not isinstance(v, dict):
        r.errors.append("police_request must be an object")
        return v
    out = dict(v)
    for k in ("lead_time_business_days", "lead_time_hours", "min_hours"):
        if k in v:
            try:
                out[k] = int(v[k])
            except (TypeError, ValueError):
                r.errors.append(f"{k} must be a whole number")
    return out


def _dict(name):
    def f(v, r: Result):
        if not isinstance(v, dict):
            r.errors.append(f"{name} must be an object")
        return v
    return f


def _positive_number(v, r: Result):
    try:
        n = float(v)
        if n <= 0:
            raise ValueError
        return int(n) if n == int(n) else n
    except (TypeError, ValueError):
        r.errors.append("must be a positive number")
        return v


def _text(v, r: Result):
    if isinstance(v, (dict, list)):
        return v
    return str(v)


@dataclass
class KeySpec:
    label: str
    help: str
    list_item: bool
    used_by_planner: bool
    check: Callable[[Any, Result], Any]
    example: Any


KEYS: dict[str, KeySpec] = {
    "peak_hours": KeySpec("Peak-hour restrictions", "Weekday windows when restrictions/lane closures aren't allowed, by road class.", False, True, _peak_hours,
                          {"road_class": ["arterial", "collector"], "weekdays": ["07:00-08:30", "15:30-18:30"], "effect": "no_restrictions", "exceptions": "approved by City Traffic Engineer"}),
    "police_required": KeySpec("Police officer trigger", "When a uniformed/off-duty officer is required.", True, True, _police_item,
                               {"when": {"within_ft_of_signalized_intersection": 300}, "role": "extra-duty police officer"}),
    "required_devices": KeySpec("Required devices", "Devices required under conditions (arrow board, signs, message boards).", True, True, _device_item,
                                {"when": {"road_class": ["arterial"], "lane_closure": True}, "devices": ["arrowboard"]}),
    "required_personnel": KeySpec("Required personnel", "People required on site under conditions.", True, False, _personnel_item,
                                  {"when": {"road_class": ["arterial"], "installing_devices": True}, "personnel": "ATSSA certified Traffic Control Supervisor on site"}),
    "police_request": KeySpec("Police booking", "How to book officers: lead time and phone.", False, True, _police_request,
                              {"lead_time_business_days": 5, "phone": "480-555-0100"}),
    "work_hours": KeySpec("Allowed work hours", "Construction hours (noise ordinance), seasons as MM-DD..MM-DD.", False, True, _work_hours,
                          {"residential_within_ft": 500, "residential": {"04-15..10-15": "06:00-19:00"}, "weekends_holidays": "07:00-19:00", "outside_hours": "written authorization required"}),
    "night_work": KeySpec("Night work", "Night definition and what night work requires.", False, True, _night_work,
                          {"definition": "19:00-06:00", "requires": ["written_authorization_letter"]}),
    "tcp_submittal": KeySpec("TCP submittal", "Lead time, where to submit, who may prepare, required contents.", False, True, _dict("tcp_submittal"),
                             {"lead_time": "3 full working days", "email": "permits@example.gov", "preparer": "ATSSA-certified designer"}),
    "flagging": KeySpec("Flagging", "Who may flag.", False, True, _dict("flagging"), {"allowed": ["ATSSA certified flaggers"]}),
    "road_closure": KeySpec("Full road closures", "Approval, lead time, notices, detours.", False, False, _dict("road_closure"), {"lead_time_days": 20, "detour_plan": "required"}),
    "school_zone": KeySpec("School zones", "How school zones are handled in work zones.", False, True, _dict("school_zone"), {"school_crosswalks": "must remain open"}),
    "pedestrian": KeySpec("Pedestrians", "Pedestrian/transit accommodation.", False, False, _dict("pedestrian"), {"detour": "delineated detour"}),
    "fees": KeySpec("Fees", "Permit and restriction fees.", False, False, _dict("fees"), {"tcp_review": 50}),
    "contacts": KeySpec("Contacts", "Agency phone numbers and emails.", False, False, _dict("contacts"), {"traffic_engineering": "480-555-0100"}),
    "min_work_area_ft": KeySpec("Minimum work area", "Minimum work-area length in feet.", False, True, _positive_number, 250),
    "device_spacing": KeySpec("Device spacing", "Channelizing device spacing.", False, True, _dict("device_spacing"), {"posted_ge_40mph": {"taper_ft": 40, "tangent_ft": 80}}),
    "speed_reduction": KeySpec("Speed reduction", "Work zone speed limit rules.", False, True, _dict("speed_reduction"), {"max_mph_without_approval": 10}),
    "note": KeySpec("General note", "A rule the planner doesn't automate yet; shown on the user checklist.", False, False, _text, "Copy of approved TCP must be on site."),
}

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def check_value(key: str, value: Any) -> Result:
    r = Result(value=value)
    spec = KEYS.get(key)
    if not KEY_RE.match(key or ""):
        r.errors.append("rule key must be lowercase letters, digits, and underscores")
        return r
    if spec is None:
        r.warnings.append(f"'{key}' isn't a rule the planner understands yet; it will be stored and listed on the user checklist only.")
        return r
    r.value = spec.check(value, r)
    if not spec.used_by_planner:
        r.warnings.append(f"{spec.label} is stored for reference and the user checklist; the planner doesn't apply it automatically yet.")
    return r


def schema_doc() -> str:
    """Compact description of rule keys for the AI assistant prompt."""
    import json

    lines = []
    for k, s in KEYS.items():
        lines.append(f"- {k}{' (list item; use op add_item)' if s.list_item else ''}: {s.help} Example value: {json.dumps(s.example)}")
    lines.append("Conditions allowed in 'when': " + "; ".join(f"{k} = {v}" for k, v in CONDITIONS.items()))
    return "\n".join(lines)
