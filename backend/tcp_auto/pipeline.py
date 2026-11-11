"""Run the planning stages for a project: rules -> timeline -> layout -> compliance."""

from __future__ import annotations

from .compliance.checks import check
from .layout.generator import generate
from .models import ComplianceIssue, Project, TcpPlan
from .rules.engine import ResolvedRules, resolve
from .timeline.schedule import TimelineResult, analyze


class PlanInputError(ValueError):
    pass


def timeline_for(project: Project, rules: ResolvedRules) -> TimelineResult:
    road = project.road
    center = project.work_center or road.centerline[0]
    return analyze(
        project.details.phases,
        rules,
        center.lat,
        center.lon,
        road.road_class.value,
        lane_closure=project.details.work_position == "lane",
        near_residential=project.details.near_residential,
    )


def build_plan(project: Project) -> tuple[TcpPlan, ResolvedRules, TimelineResult]:
    if not project.road or len(project.road.centerline) < 2:
        raise PlanInputError("Draw the road centerline (at least two points) before generating a plan.")
    if not project.work_center:
        raise PlanInputError("Set the work location on the map before generating a plan.")
    rules = resolve(project.details)
    tl = timeline_for(project, rules)
    plan = generate(project.road, project.details, rules, project.work_center, project.work_extent_ft, tl)
    plan.issues = plan.issues + tl.issues + [ComplianceIssue(severity="info", message=w) for w in rules.warnings]
    if not project.road.speed_confirmed:
        plan.issues.append(ComplianceIssue(severity="warning", message=f"Posted speed ({project.road.speed_mph} mph) is not confirmed. Speed drives taper, buffer, and sign spacing."))
    plan.issues += check(plan, project.road)
    return plan, rules, tl


def recheck(project: Project) -> TcpPlan:
    """Re-run compliance after edits, keeping generation-time issues that don't depend on positions."""
    plan = project.plan
    keep = [i for i in plan.issues if i.severity == "info" or "Phase" in i.message or "speed" in i.message.lower() and "confirmed" in i.message or "Intersection" in i.message or "one-way" in i.message]
    plan.issues = keep + check(plan, project.road)
    return plan
