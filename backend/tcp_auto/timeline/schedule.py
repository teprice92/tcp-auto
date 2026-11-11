"""Timeline checks: night work, peak-hour conflicts, allowed work hours, duration category."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..models import ComplianceIssue, Phase
from ..rules.engine import ResolvedRules

ARIZONA_TZ = ZoneInfo("America/Phoenix")  # no daylight saving time


def sun_times(d: date, lat: float, lon: float, tz: ZoneInfo = ARIZONA_TZ) -> tuple[time, time]:
    """Approximate sunrise and sunset (NOAA algorithm, ~1-2 min accuracy)."""
    n = d.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )
    zenith = math.radians(90.833)
    la = math.radians(lat)
    cos_ha = math.cos(zenith) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    sunrise_utc = 720 - 4 * (lon + ha) - eqtime
    sunset_utc = 720 - 4 * (lon - ha) - eqtime
    base = datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("UTC"))

    def to_local(minutes: float) -> time:
        return (base + timedelta(minutes=minutes)).astimezone(tz).time().replace(second=0, microsecond=0)

    return to_local(sunrise_utc), to_local(sunset_utc)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _parse_window(w: str) -> tuple[int, int]:
    a, b = w.split("-")
    ha, ma = (int(x) for x in a.split(":"))
    hb, mb = (int(x) for x in b.split(":"))
    return ha * 60 + ma, hb * 60 + mb


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Overlap of two same-day minute windows; a window may wrap past midnight."""

    def parts(w):
        s, e = w
        return [(s, e)] if e > s else [(s, 24 * 60), (0, e)]

    return any(s1 < e2 and s2 < e1 for s1, e1 in parts(a) for s2, e2 in parts(b))


def phase_days(p: Phase) -> list[date]:
    out, d = [], p.start_date
    while d <= p.end_date:
        if d.weekday() in p.days:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass
class TimelineResult:
    night: bool = False
    night_phases: list[str] = field(default_factory=list)
    during_peak: bool = False
    duration_days: int = 0
    duration: str = "short_term"
    issues: list[ComplianceIssue] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    sun: dict[str, str] = field(default_factory=dict)


def analyze(
    phases: list[Phase],
    rules: ResolvedRules,
    lat: float,
    lon: float,
    road_class: str,
    lane_closure: bool,
    near_residential: bool,
) -> TimelineResult:
    r = TimelineResult()
    if not phases:
        r.issues.append(ComplianceIssue(severity="warning", message="No timeline entered: add start/end dates and work hours."))
        return r

    all_days: set[date] = set()
    night_def = None
    nw = rules.get("night_work") or {}
    if isinstance(nw, dict) and isinstance(nw.get("definition"), str):
        night_def = _parse_window(nw["definition"])

    peak = rules.get("peak_hours")
    peak_rule = rules.rule("peak_hours")

    for p in phases:
        days = phase_days(p)
        all_days.update(days)
        win = (_minutes(p.start_time), _minutes(p.end_time))
        long_hours = (win[1] - win[0]) % (24 * 60) > 12 * 60

        # Night: overlaps sunset-to-sunrise on any working day, or the agency's night definition
        is_night = False
        for d in days[:31]:
            rise, set_ = sun_times(d, lat, lon)
            if _overlaps(win, (_minutes(set_), _minutes(rise))):
                is_night = True
                r.sun = {"sunrise": rise.strftime("%H:%M"), "sunset": set_.strftime("%H:%M")}
                break
        if night_def and _overlaps(win, night_def):
            is_night = True
        if is_night:
            r.night = True
            r.night_phases.append(p.name)

        # Peak-hour restrictions
        if isinstance(peak, dict):
            classes = peak.get("road_class", [])
            effect = peak.get("effect", "no_restrictions")
            applies = road_class in classes and (lane_closure or effect == "no_restrictions")
            weekday_work = any(d.weekday() < 5 for d in days)
            for w in peak.get("weekdays", []):
                if applies and weekday_work and _overlaps(win, _parse_window(w)):
                    r.during_peak = True
                    r.issues.append(
                        ComplianceIssue(
                            severity="error",
                            message=(
                                f"Phase '{p.name}' ({p.start_time:%H:%M}-{p.end_time:%H:%M}) overlaps the peak period "
                                f"{w} when {effect.replace('_', ' ')} are allowed on {road_class} streets"
                                f"{' (unless approved: ' + peak['exceptions'] + ')' if peak.get('exceptions') else ''}."
                            ),
                            rule_ref=peak_rule.cite if peak_rule else None,
                        )
                    )
        if long_hours:
            r.issues.append(
                ComplianceIssue(
                    severity="info",
                    message=f"Phase '{p.name}' runs more than 12 hours a day; confirm whether the setup stays in place overnight.",
                )
            )

        # Allowed construction hours (e.g., Tempe City Code 20-8)
        wh = rules.get("work_hours")
        wh_rule = rules.rule("work_hours")
        if isinstance(wh, dict):
            for d in days[:366]:
                allowed = _allowed_window(wh, d, near_residential)
                if allowed and not _within(win, allowed):
                    r.issues.append(
                        ComplianceIssue(
                            severity="warning",
                            message=(
                                f"Phase '{p.name}' works outside allowed construction hours on {d:%a %b %d} "
                                f"(allowed {allowed[0] // 60:02d}:{allowed[0] % 60:02d}-{allowed[1] // 60:02d}:{allowed[1] % 60:02d}). "
                                f"{wh.get('outside_hours', 'Written authorization required.')}"
                            ),
                            rule_ref=wh_rule.cite if wh_rule else None,
                        )
                    )
                    break

    # MUTCD duration categories (as quoted in the ADOT TTC Design Guidelines, p.13)
    r.duration_days = len(all_days)
    longest = max((_minutes(p.end_time) - _minutes(p.start_time)) % 1440 for p in phases)
    if r.duration_days > 3:
        r.duration = "long_term"
    elif r.duration_days > 1 or (r.night and longest > 60):
        r.duration = "intermediate_term"
    elif longest <= 60:
        r.duration = "short_duration"
    else:
        r.duration = "short_term"

    if r.night:
        if isinstance(nw, dict):
            for req in nw.get("requires", []) or []:
                r.checklist.append(
                    {"written_authorization_letter": "Night work: obtain a written authorization letter from the city (noise/work hours)."}.get(
                        req, f"Night work: {req.replace('_', ' ')}"
                    )
                )
        r.checklist.append("Night work: lighting for flagger stations and the work area; flashing lights on signs.")
    return r


def _allowed_window(wh: dict, d: date, near_res: bool) -> tuple[int, int] | None:
    if d.weekday() >= 5 and wh.get("weekends_holidays"):
        return _parse_window(wh["weekends_holidays"])
    if near_res and isinstance(wh.get("residential"), dict):
        for season, w in wh["residential"].items():
            a, b = season.split("..")
            ma, da = (int(x) for x in a.split("-"))
            mb, db = (int(x) for x in b.split("-"))
            md = (d.month, d.day)
            inside = (ma, da) <= md <= (mb, db) if (ma, da) <= (mb, db) else (md >= (ma, da) or md <= (mb, db))
            if inside:
                return _parse_window(w)
    if not near_res and wh.get("commercial_industrial"):
        return _parse_window(wh["commercial_industrial"])
    return None


def _within(win: tuple[int, int], allowed: tuple[int, int]) -> bool:
    s, e = win
    a, b = allowed
    return e > s and a <= s and e <= b
