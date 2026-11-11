from datetime import date, time

from tcp_auto.compliance.checks import check
from tcp_auto.layout.generator import buffer_ft, merging_taper_ft
from tcp_auto.models import DeviceType, Phase
from tcp_auto.pipeline import build_plan, recheck


def test_taper_formula():
    assert merging_taper_ft(12, 40) == 12 * 40 * 40 / 60  # 320
    assert merging_taper_ft(12, 45) == 540
    assert buffer_ft(35) == 250 and buffer_ft(33) == 250


def test_multilane_closure(make_project):
    p = make_project()
    plan, _, _ = build_plan(p)
    assert plan.template == "lane_closure_multilane"
    assert plan.dimensions.work_area_ft >= 250
    assert plan.dimensions.taper_ft == 320
    assert plan.dimensions.taper_spacing_ft == 40 and plan.dimensions.tangent_spacing_ft == 80  # ADOT >= 40 mph
    codes = [d.code for d in plan.devices if d.group == "advance_warning"]
    assert codes == ["W4-2R", "W20-5R", "W20-1"]
    assert any(d.type == DeviceType.arrow_board for d in plan.devices)
    assert not [i for i in plan.issues if i.severity == "error"], plan.issues


def test_adot_spacing_at_45mph(make_project):
    plan, _, _ = build_plan(make_project(road_kw=dict(speed_mph=45)))
    assert (plan.dimensions.taper_spacing_ft, plan.dimensions.tangent_spacing_ft) == (40, 80)
    plan, _, _ = build_plan(make_project(road_kw=dict(speed_mph=30)))
    assert (plan.dimensions.taper_spacing_ft, plan.dimensions.tangent_spacing_ft) == (30, 60)


def test_two_lane_flagger(make_project):
    p = make_project(road_kw=dict(lanes_forward=1, lanes_backward=1, speed_mph=30, road_class="collector"))
    plan, _, _ = build_plan(p)
    assert plan.template == "two_lane_flagger"
    assert sum(d.type == DeviceType.flagger for d in plan.devices) == 2
    assert {"W20-7", "W20-4", "W20-1"} <= {d.code for d in plan.devices}
    assert plan.dimensions.taper_ft == 50
    assert not [i for i in plan.issues if i.severity == "error"], plan.issues


def test_shoulder_work(make_project):
    p = make_project(work_position="shoulder", road_kw=dict(speed_mph=35))
    plan, _, _ = build_plan(p)
    assert plan.template == "shoulder"
    assert [d.code for d in plan.devices if d.group == "advance_warning"] == ["W21-5", "W20-1"]


def test_min_work_area_and_extent(make_project):
    p = make_project()
    p.work_extent_ft = 400
    plan, _, _ = build_plan(p)
    assert plan.dimensions.work_area_ft == 450  # extent + 2 x 25 ft clearance


def test_gilbert_police_near_signal(make_project, signal_at):
    p = make_project(city="Gilbert", road_kw=dict(intersections=signal_at(2500)))  # work ends ~2405 ft
    plan, _, _ = build_plan(p)
    assert any(r.kind == "police" and r.required for r in plan.requirements)
    assert any(d.type == DeviceType.police for d in plan.devices)
    assert any("Intersection" in i.message for i in plan.issues)


def test_night_work_uses_drums_and_lights(make_project):
    p = make_project(phases=[Phase(name="Night", start_date=date(2026, 12, 1), end_date=date(2026, 12, 1), start_time=time(20, 0), end_time=time(23, 0))])
    plan, _, tl = build_plan(p)
    assert plan.night and tl.night
    assert not any(d.type == DeviceType.cone for d in plan.devices)
    assert any(d.type == DeviceType.light_tower for d in plan.devices)
    assert all(d.lights for d in plan.devices if d.group == "advance_warning")


def test_peak_hour_conflict_tempe(make_project):
    p = make_project(phases=[Phase(name="Work", start_date=date(2026, 12, 1), end_date=date(2026, 12, 1), start_time=time(7, 0), end_time=time(12, 0))])
    plan, _, _ = build_plan(p)
    assert any(i.severity == "error" and "peak" in i.message for i in plan.issues)


def test_tempe_work_hours_weekend(make_project):
    # Saturday 6:00 start is before Tempe's 7:00 weekend limit near homes
    p = make_project(phases=[Phase(name="Sat", start_date=date(2026, 12, 5), end_date=date(2026, 12, 5), start_time=time(6, 0), end_time=time(12, 0), days=[5])])
    plan, _, _ = build_plan(p)
    assert any("outside allowed construction hours" in i.message for i in plan.issues)


def test_moving_a_sign_too_close_is_flagged(make_project):
    p = make_project()
    p.plan, _, _ = build_plan(p)
    w42 = next(d for d in p.plan.devices if d.code == "W4-2R")
    taper_start = max((d for d in p.plan.devices if d.group == "taper" and d.type in (DeviceType.cone, DeviceType.drum)), key=lambda d: p.plan.dimensions.work_start_station_ft - d.station_ft)
    w42.lat, w42.lon = taper_start.lat, taper_start.lon - 0.0002  # ~60 ft upstream
    recheck(p)
    assert any(i.severity == "error" and "W4-2R" in i.message for i in p.plan.issues)


def test_shortened_taper_is_flagged(make_project):
    p = make_project()
    p.plan, _, _ = build_plan(p)
    taper = [d for d in p.plan.devices if d.group == "taper" and d.type in (DeviceType.cone, DeviceType.drum)]
    far = min(taper, key=lambda d: d.station_ft)
    near = max(taper, key=lambda d: d.station_ft)
    far.lon = near.lon - 0.0003  # ~90 ft taper
    issues = check(p.plan, p.road)
    assert any("Taper is" in i.message for i in issues)
