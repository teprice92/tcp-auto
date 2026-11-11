"""OpenStreetMap lookups (Overpass for roads, Nominatim for addresses).

Everything returned here is a *suggestion* with its source recorded; the user confirms or edits it.
The functions raise ``OSMUnavailable`` when the network or service can't be reached, so the app
keeps working with manual input.
"""

from __future__ import annotations

import os
import re

import httpx

from ..geo import Centerline, haversine_ft
from ..models import Intersection, LatLon, RoadClass, RoadContext

OVERPASS_URL = os.environ.get("TCP_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NOMINATIM_URL = os.environ.get("TCP_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
USER_AGENT = os.environ.get("TCP_USER_AGENT", "tcp-auto/0.1 (traffic control planning tool)")

CLASS_MAP = {
    "motorway": RoadClass.highway, "trunk": RoadClass.highway, "motorway_link": RoadClass.highway, "trunk_link": RoadClass.highway,
    "primary": RoadClass.arterial, "primary_link": RoadClass.arterial, "secondary": RoadClass.arterial,
    "tertiary": RoadClass.collector, "secondary_link": RoadClass.collector, "tertiary_link": RoadClass.collector,
    "residential": RoadClass.local, "unclassified": RoadClass.local, "living_street": RoadClass.local, "service": RoadClass.local,
}
DRIVABLE = set(CLASS_MAP)
DEFAULT_SPEED = {RoadClass.highway: 55, RoadClass.arterial: 45, RoadClass.collector: 35, RoadClass.local: 25}


class OSMUnavailable(RuntimeError):
    pass


def _post(query: str, timeout: float = 25.0) -> dict:
    try:
        r = httpx.post(OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # network blocked, timeout, bad response
        raise OSMUnavailable(str(e)) from e


def _speed(tags: dict) -> int | None:
    m = re.match(r"(\d+)\s*(mph)?", tags.get("maxspeed", ""))
    return int(m.group(1)) if m else None


def _stitch(main: dict, ways: list[dict], max_ways: int = 12) -> tuple[list, list]:
    """OSM splits streets into short ways at intersections. Join same-named ways that share end
    nodes (in either direction) so the centerline covers the whole work zone."""
    name = main.get("tags", {}).get("name")
    nodes = list(main.get("nodes") or [])
    geom = list(main["geometry"])
    if not name or len(nodes) != len(geom):
        return nodes, geom
    pool = [w for w in ways if w["id"] != main["id"] and w.get("tags", {}).get("name") == name
            and w.get("tags", {}).get("oneway") == main.get("tags", {}).get("oneway")
            and len(w.get("nodes") or []) == len(w["geometry"])]
    for _ in range(max_ways):
        grown = False
        for w in list(pool):
            wn, wg = w["nodes"], w["geometry"]
            if wn[0] == nodes[-1]:
                nodes, geom = nodes + wn[1:], geom + wg[1:]
            elif wn[-1] == nodes[-1]:
                nodes, geom = nodes + wn[-2::-1], geom + wg[-2::-1]
            elif wn[-1] == nodes[0]:
                nodes, geom = wn[:-1] + nodes, wg[:-1] + geom
            elif wn[0] == nodes[0]:
                nodes, geom = wn[:0:-1] + nodes, wg[:0:-1] + geom
            else:
                continue
            pool.remove(w)
            grown = True
        if not grown:
            break
    return nodes, geom


def overpass_query(lat: float, lon: float, radius_m: int = 60) -> str:
    """Ways near the point (with geometry), connected ways of the same street, signals, schools."""
    return f"""
[out:json][timeout:25];
way(around:{radius_m},{lat},{lon})[highway] -> .main;
.main out body geom;
way(around:900,{lat},{lon})[highway] -> .near;
.near out body geom;
node(around:900,{lat},{lon})[highway=traffic_signals];
out body;
nwr(around:250,{lat},{lon})[amenity=school];
out center tags;
"""


def parse_overpass(data: dict, lat: float, lon: float) -> tuple[RoadContext, dict]:
    """Pick the nearest drivable way and build a RoadContext suggestion."""
    elements = data.get("elements", [])
    ways = list({e["id"]: e for e in elements if e["type"] == "way" and e.get("geometry") and e.get("tags", {}).get("highway") in DRIVABLE}.values())
    if not ways:
        raise LookupError("No drivable road found near this point.")
    here = LatLon(lat=lat, lon=lon)

    def dist(w):
        cl = Centerline([LatLon(lat=g["lat"], lon=g["lon"]) for g in w["geometry"]])
        return abs(cl.project(here)[1])

    main = min(ways, key=dist)
    tags = main.get("tags", {})
    node_ids, geom = _stitch(main, ways)
    main = {**main, "nodes": node_ids}
    pts = [LatLon(lat=g["lat"], lon=g["lon"]) for g in geom]
    cl = Centerline(pts)
    rclass = CLASS_MAP.get(tags.get("highway"), RoadClass.collector)
    one_way = tags.get("oneway") in ("yes", "1", "true")
    lanes = int(re.sub(r"\D", "", tags.get("lanes", "")) or 0) or (1 if one_way else 2)
    lf = int(tags.get("lanes:forward", 0) or 0)
    lb = int(tags.get("lanes:backward", 0) or 0)
    if one_way:
        lf, lb = lanes, 0
    elif not (lf and lb):
        lf = max(1, lanes // 2)
        lb = max(1, lanes - lf)
    speed = _speed(tags)
    sources = {"centerline": "osm", "lanes": "osm" if "lanes" in tags else "rule_default", "road_class": "osm", "speed_mph": "osm" if speed else "rule_default"}

    # Intersections: nodes of the main way shared with other drivable ways
    node_ids = main.get("nodes", [])
    signals = {e["id"] for e in elements if e["type"] == "node" and e.get("tags", {}).get("highway") == "traffic_signals"}
    others: dict[int, str] = {}
    for e in elements:
        if e["type"] == "way" and e["id"] != main["id"] and e.get("tags", {}).get("highway") in DRIVABLE:
            nm = e.get("tags", {}).get("name", "")
            if nm and nm == tags.get("name"):
                continue
            for nid in e.get("nodes", []):
                others.setdefault(nid, nm)
    ints = []
    for i, nid in enumerate(node_ids):
        if nid in others and i < len(pts):
            st, _ = cl.project(pts[i])
            ints.append(Intersection(station_ft=round(st, 1), cross_street=others[nid], signalized=nid in signals))
    # signals tagged on nodes near (not on) the way, e.g. at dual carriageways
    sig_nodes = [e for e in elements if e["type"] == "node" and e["id"] in signals and e["id"] not in node_ids]
    for n in sig_nodes:
        st, off = cl.project(LatLon(lat=n["lat"], lon=n["lon"]))
        if abs(off) < 80 and not any(abs(st - ix.station_ft) < 120 for ix in ints):
            ints.append(Intersection(station_ft=round(st, 1), cross_street="", signalized=True))

    schools = []
    for e in elements:
        if e.get("tags", {}).get("amenity") == "school":
            c = e.get("center") or ({"lat": e.get("lat"), "lon": e.get("lon")} if e.get("lat") else None)
            if c:
                schools.append({"name": e["tags"].get("name", "School"), "distance_ft": round(haversine_ft(here, LatLon(lat=c["lat"], lon=c["lon"])))})
    road = RoadContext(
        name=tags.get("name", ""), centerline=pts, speed_mph=speed or DEFAULT_SPEED[rclass], speed_confirmed=False,
        lanes_forward=lf, lanes_backward=lb, one_way=one_way, road_class=rclass,
        has_bike_lane=any(k.startswith("cycleway") and v in ("lane", "track") for k, v in tags.items()),
        has_sidewalk=tags.get("sidewalk", "both") != "no",
        intersections=sorted(ints, key=lambda i: i.station_ft), sources=sources,
    )
    return road, {"schools": sorted(schools, key=lambda s: s["distance_ft"]), "osm_way_id": main["id"], "highway": tags.get("highway")}


def lookup_road(lat: float, lon: float) -> tuple[RoadContext, dict]:
    return parse_overpass(_post(overpass_query(lat, lon)), lat, lon)


def geocode(q: str) -> list[dict]:
    try:
        r = httpx.get(NOMINATIM_URL, params={"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "us"}, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        return [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]
    except Exception as e:
        raise OSMUnavailable(str(e)) from e
