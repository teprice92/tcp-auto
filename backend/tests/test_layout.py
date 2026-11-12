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


def test_divided_road_follows_carriageway(make_project):
    """Around a median, lanes (and the closure) are pushed out to the carriageway, and project() undoes it."""
    from tcp_auto.geo import Centerline
    from tcp_auto.models import LatLon, MedianPoint

    median = [MedianPoint(station_ft=0, width_ft=0), MedianPoint(station_ft=1500, width_ft=0),
              MedianPoint(station_ft=1700, width_ft=40), MedianPoint(station_ft=4560, width_ft=40)]
    p = make_project(road_kw=dict(median=median, divided=True))
    cl = Centerline.for_road(p.road)
    assert cl.median_half(1000) == 0 and cl.median_half(1600) == 10 and cl.median_half(3000) == 20
    # a point 30 ft right of center lands 50 ft out where the median is 40 ft wide
    x0, y0 = cl.point_xy(3000, 0)
    x1, y1 = cl.point_xy(3000, -30)
    assert abs(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 - 50) < 0.5
    s, off = cl.project(cl.point(3000, -30))
    assert abs(s - 3000) < 0.5 and abs(off + 30) < 0.5

    plain, _, _ = build_plan(make_project())
    divided, _, _ = build_plan(p)
    assert divided.template == plain.template == "lane_closure_multilane"
    assert len([z for z in divided.zones if z.kind == "roadway"]) == 2  # one per carriageway
    # cones in the median section sit farther from the centerline than on the undivided road
    def dist(c, d):  # distance from the centerline, median included
        s, off = c.project(LatLon(lat=d.lat, lon=d.lon))
        return abs(off) + c.median_half(s)

    def max_off(plan):
        return max(dist(cl, d) for d in plan.devices if d.type == DeviceType.cone)
    assert max_off(divided) > max_off(plain) + 15


def test_center_turn_lane_shift(make_project):
    """1 + center turn lane + 1: traffic shifts into the center lane (no flaggers), with a shifting taper."""
    from tcp_auto.geo import Centerline
    from tcp_auto.models import LatLon

    p = make_project(road_kw=dict(lanes_forward=1, lanes_backward=1, center_turn_lane=True, speed_mph=35, road_class="collector"))
    plan, _, _ = build_plan(p)
    assert plan.template == "lane_shift_twltl"
    assert plan.dimensions.taper_ft == round(0.5 * 12 * 35 * 35 / 60)  # 0.5 L
    assert not any(d.type == DeviceType.flagger for d in plan.devices)
    codes = [d.code for d in plan.devices if d.group == "advance_warning"]
    assert codes == ["W1-4L", "W20-5R", "W20-1"]
    assert any(z.kind == "center_lane" for z in plan.zones)
    cl = Centerline.for_road(p.road)
    # taper ends at the closed lane's inside line (6 ft right of center = center-lane edge), not mid center lane
    last = min((d for d in plan.devices if d.group == "taper"), key=lambda d: abs(d.station_ft - plan.dimensions.work_start_station_ft))
    x0, y0 = cl.point_xy(last.station_ft, 0)
    x1, y1 = cl.frame.to_xy(LatLon(lat=last.lat, lon=last.lon))
    assert abs(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 - 6) < 0.5
    # center-lane separation devices sit on the opposing edge of the center lane
    sep = [d for d in plan.devices if d.group == "centerline"]
    assert len(sep) >= 5
    x2, y2 = cl.frame.to_xy(LatLon(lat=sep[2].lat, lon=sep[2].lon))
    x3, y3 = cl.point_xy(sep[2].station_ft, 0)
    assert abs(((x2 - x3) ** 2 + (y2 - y3) ** 2) ** 0.5 - 6) < 0.5
    assert not [i for i in plan.issues if i.severity == "error"], plan.issues


def test_three_plus_one_plus_three(make_project):
    """3 + center turn lane + 3 (7 lanes): curb lane closure, lanes pushed out past the center lane."""
    from tcp_auto.layout.generator import lane_config

    p = make_project(road_kw=dict(lanes_forward=3, lanes_backward=3, center_turn_lane=True, speed_mph=45))
    assert lane_config(p.road) == "7-lane road: 3 lanes each way + center turn lane"
    plan, _, _ = build_plan(p)
    assert plan.template == "lane_closure_multilane"
    work = next(z for z in plan.zones if z.kind == "work_area")
    from tcp_auto.geo import Centerline

    cl = Centerline.for_road(p.road)
    offs = sorted(cl.project(q)[1] for q in work.polygon)
    assert abs(offs[0] - 24) < 0.5 and abs(offs[-1] - 36) < 0.5  # third lane, measured from the center-lane edge
    x0, y0 = cl.point_xy(plan.dimensions.work_start_station_ft, 0)
    x1, y1 = cl.point_xy(plan.dimensions.work_start_station_ft, 36)
    assert abs(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 - 42) < 0.5  # 6 ft half center lane + 3 x 12 ft
    assert not [i for i in plan.issues if i.severity == "error"], plan.issues


def test_far_side_closure_is_drivers_right_lane(make_project):
    """Work on the opposing side of a two-way road closes that direction's curb lane: the driver's RIGHT lane."""
    from tcp_auto.report.narrative import explain

    p = make_project(side="left")
    plan, _, _ = build_plan(p)
    codes = [d.code for d in plan.devices if d.group == "advance_warning"]
    assert codes == ["W4-2R", "W20-5R", "W20-1"]
    assert "westbound right lane" in explain(p, plan)[0] and "merge left" in explain(p, plan)[0]
    p = make_project(side="left", road_kw=dict(lanes_forward=1, lanes_backward=1, center_turn_lane=True, speed_mph=30))
    plan, _, _ = build_plan(p)
    assert [d.code for d in plan.devices if d.group == "advance_warning"][:2] == ["W1-4L", "W20-5R"]
    p = make_project(side="left", road_kw=dict(one_way=True, lanes_forward=3, lanes_backward=0))
    plan, _, _ = build_plan(p)
    assert [d.code for d in plan.devices if d.group == "advance_warning"][:2] == ["W4-2L", "W20-5L"]  # one-way: really the left lane
