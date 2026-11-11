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
