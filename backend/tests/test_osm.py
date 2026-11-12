from tcp_auto.site.osm import parse_overpass


def test_parse_overpass_fixture():
    lat, lon = 33.4215, -111.9125
    data = {"elements": [
        {"type": "way", "id": 1, "nodes": [10, 11, 12], "tags": {"highway": "primary", "name": "E University Dr", "lanes": "4", "maxspeed": "40 mph"},
         "geometry": [{"lat": 33.4215, "lon": -111.92}, {"lat": 33.4215, "lon": -111.9125}, {"lat": 33.4215, "lon": -111.905}]},
        {"type": "way", "id": 2, "nodes": [20, 11, 21], "tags": {"highway": "secondary", "name": "S Rural Rd"}},
        {"type": "node", "id": 11, "lat": 33.4215, "lon": -111.9125, "tags": {"highway": "traffic_signals"}},
        {"type": "way", "id": 3, "center": {"lat": 33.4225, "lon": -111.9125}, "tags": {"amenity": "school", "name": "Test Elementary"}},
    ]}
    road, extra = parse_overpass(data, lat, lon)
    assert road.name == "E University Dr" and road.speed_mph == 40
    assert road.lanes_forward == 2 and road.lanes_backward == 2
    assert road.road_class.value == "arterial" and not road.speed_confirmed
    assert len(road.intersections) == 1 and road.intersections[0].signalized and road.intersections[0].cross_street == "S Rural Rd"
    assert extra["schools"][0]["name"] == "Test Elementary" and extra["schools"][0]["distance_ft"] < 400


def test_stitches_split_street():
    """A street split into three ways (one reversed) becomes one centerline through all of them."""
    lat = 33.4215
    g = lambda lon: {"lat": lat, "lon": lon}
    data = {"elements": [
        {"type": "way", "id": 1, "nodes": [1, 2], "tags": {"highway": "primary", "name": "E University Dr"}, "geometry": [g(-111.915), g(-111.912)]},
        {"type": "way", "id": 2, "nodes": [3, 2], "tags": {"highway": "primary", "name": "E University Dr"}, "geometry": [g(-111.909), g(-111.912)]},
        {"type": "way", "id": 3, "nodes": [4, 1], "tags": {"highway": "primary", "name": "E University Dr"}, "geometry": [g(-111.918), g(-111.915)]},
        {"type": "way", "id": 1, "nodes": [1, 2], "tags": {"highway": "primary", "name": "E University Dr"}, "geometry": [g(-111.915), g(-111.912)]},  # duplicate from 2nd query set
        {"type": "way", "id": 9, "nodes": [2, 7], "tags": {"highway": "secondary", "name": "S Rural Rd"}, "geometry": [g(-111.912), {"lat": 33.43, "lon": -111.912}]},
    ]}
    road, _ = parse_overpass(data, lat, -111.913)
    lons = [p.lon for p in road.centerline]
    assert lons[0] == -111.918 and lons[-1] == -111.909 and len(lons) == 4
    assert [i.cross_street for i in road.intersections] == ["S Rural Rd"]


def test_pairs_divided_road_carriageways():
    """A divided road mapped as two one-way ways (plus a two-way stretch before the split) becomes one
    road with a median profile, both directions' lanes and one intersection per cross street."""
    from tcp_auto.geo import Centerline
    from tcp_auto.models import LatLon

    lat, d = 33.3644, 0.00008  # carriageways ~29 ft either side of the middle -> ~58 ft apart
    g = lambda la, lo: {"lat": la, "lon": lo}
    name = {"highway": "secondary", "name": "E Guadalupe Rd"}
    data = {"elements": [
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {**name, "lanes": "4"}, "geometry": [g(lat, -111.800), g(lat, -111.796)]},
        {"type": "way", "id": 11, "nodes": [2, 3, 32, 4], "tags": {**name, "oneway": "yes", "lanes": "2"},
         "geometry": [g(lat, -111.796), g(lat - d, -111.795), g(lat - d, -111.790), g(lat - d, -111.788)]},
        {"type": "way", "id": 12, "nodes": [5, 31, 6, 2], "tags": {**name, "oneway": "yes", "lanes": "2"},
         "geometry": [g(lat + d, -111.788), g(lat + d, -111.790), g(lat + d, -111.795), g(lat, -111.796)]},
        {"type": "way", "id": 20, "nodes": [30, 31, 32, 33], "tags": {"highway": "primary", "name": "N Gilbert Rd"},
         "geometry": [g(lat + 0.002, -111.790), g(lat + d, -111.790), g(lat - d, -111.790), g(lat - 0.002, -111.790)]},
        {"type": "node", "id": 31, "lat": lat + d, "lon": -111.790, "tags": {"highway": "traffic_signals"}},
        {"type": "node", "id": 32, "lat": lat - d, "lon": -111.790, "tags": {"highway": "traffic_signals"}},
    ]}
    road, extra = parse_overpass(data, lat - d, -111.792)  # a point on the eastbound carriageway
    assert extra["osm_way_id"] == 11 and extra["osm_partner_way_id"] == 12
    assert not road.one_way and road.divided and (road.lanes_forward, road.lanes_backward) == (2, 2)
    assert road.centerline[0].lon == -111.800  # continues onto the undivided stretch
    assert abs(road.centerline[-1].lat - lat) < 1e-5  # midway between the carriageways
    widths = {round(m.station_ft): m.width_ft for m in road.median}
    assert road.median[0].width_ft == 0  # undivided before the split
    assert 30 < max(widths.values()) < 38  # ~58 ft apart minus 2 lanes x 12 ft per side / 2
    assert [(i.cross_street, i.signalized) for i in road.intersections] == [("N Gilbert Rd", True)]
    # the eastbound carriageway is the right-hand roadway: its middle is 12 ft (one lane) right of the median edge
    cl = Centerline.for_road(road)
    s, off = cl.project(LatLon(lat=lat - d, lon=-111.792))
    assert abs(off - 12) < 2, off
    # and a plan built on it keeps the closure on the eastbound carriageway
    from datetime import date, time

    from tcp_auto.models import Phase, Project, ProjectDetails
    from tcp_auto.pipeline import build_plan

    road.speed_confirmed = True
    p = Project(details=ProjectDetails(city="Gilbert", work_position="lane", phases=[Phase(name="W", start_date=date(2026, 12, 1), end_date=date(2026, 12, 1),
                                                                                       start_time=time(9), end_time=time(15))]),
                road=road, work_center=LatLon(lat=lat - d, lon=-111.7915))
    plan, _, _ = build_plan(p)
    assert plan.template == "lane_closure_multilane"
    work = [z for z in plan.zones if z.kind == "work_area"][0]
    assert all(pt.lat < lat - d / 3 for pt in work.polygon), "work area should sit on the south (eastbound) roadway"


def test_center_turn_lane_from_osm():
    lat = 33.4215
    g = lambda lon: {"lat": lat, "lon": lon}
    data = {"elements": [{"type": "way", "id": 1, "nodes": [1, 2], "geometry": [g(-111.92), g(-111.905)],
                          "tags": {"highway": "secondary", "name": "E Baseline Rd", "lanes": "7", "lanes:both_ways": "1"}}]}
    road, _ = parse_overpass(data, lat, -111.91)
    assert road.center_turn_lane and (road.lanes_forward, road.lanes_backward) == (3, 3)
    data["elements"][0]["tags"] = {"highway": "tertiary", "name": "N Oak St", "lanes": "3", "turn:lanes:both_ways": "left"}
    road, _ = parse_overpass(data, lat, -111.91)
    assert road.center_turn_lane and (road.lanes_forward, road.lanes_backward) == (1, 1)
