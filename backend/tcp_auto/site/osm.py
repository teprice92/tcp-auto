"""OpenStreetMap lookups (Overpass for roads, Nominatim for addresses).

Everything returned here is a *suggestion* with its source recorded; the user confirms or edits it.
The functions raise ``OSMUnavailable`` when the network or service can't be reached, so the app
keeps working with manual input.
"""

from __future__ import annotations

import math
import os
import re

import httpx

from ..geo import Centerline, haversine_ft
from ..models import Intersection, LatLon, MedianPoint, RoadClass, RoadContext

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


def _is_oneway(tags: dict) -> bool:
    return tags.get("oneway") in ("yes", "1", "true")


def _lanes(tags: dict) -> int:
    return int(re.sub(r"\D", "", tags.get("lanes", "")) or 0)


def _pts(geom: list[dict]) -> list[LatLon]:
    return [LatLon(lat=g["lat"], lon=g["lon"]) for g in geom]


def _mid(a: LatLon, b: LatLon) -> LatLon:
    return LatLon(lat=(a.lat + b.lat) / 2, lon=(a.lon + b.lon) / 2)


def _find_partner(main: dict, main_cl: Centerline, main_nodes: list, ways: list[dict], max_sep_ft: float = 300.0) -> dict | None:
    """The other carriageway of a divided road: a same-named one-way way running the opposite direction
    alongside the main one (OSM maps each direction of a divided road as its own one-way way)."""
    name = main.get("tags", {}).get("name")
    if not name:
        return None
    taken = set(main_nodes)
    best = None
    for w in ways:
        t = w.get("tags", {})
        if w["id"] == main["id"] or t.get("name") != name or not _is_oneway(t) or set(w.get("nodes") or []) <= taken:
            continue
        pts = _pts(w["geometry"])
        offs, opposite = [], 0
        for a, b in zip(pts, pts[1:]):
            m = _mid(a, b)
            st, off = main_cl.project(m)
            if not 0 <= st <= main_cl.length:
                continue
            offs.append(abs(off))
            (hx, hy), (ax, ay), (bx, by) = main_cl.heading(st), main_cl.frame.to_xy(a), main_cl.frame.to_xy(b)
            opposite += 1 if hx * (bx - ax) + hy * (by - ay) < 0 else -1
        if not offs or opposite <= 0:
            continue
        sep = sum(offs) / len(offs)
        if sep <= max_sep_ft and (best is None or sep < best[0]):
            best = (sep, w)
    return best[1] if best else None


def _extend_undivided(ends: set, ways: list[dict], name: str, exclude: set) -> list[tuple[list, list[dict]]]:
    """Two-way stretches of the same street continuing past where the carriageways split or rejoin.
    Returns [(node ids, geometry)] each running away from the carriageway end it touches."""
    out = []
    for w in ways:
        t = w.get("tags", {})
        nodes = w.get("nodes") or []
        if w["id"] in exclude or t.get("name") != name or _is_oneway(t) or len(nodes) != len(w["geometry"]):
            continue
        if nodes[0] not in ends and nodes[-1] not in ends:
            continue
        sn, sg = _stitch(w, ways)
        if sn[0] in ends:
            out.append((sn, sg))
        elif sn[-1] in ends:
            out.append((sn[::-1], sg[::-1]))
        exclude |= {x["id"] for x in ways if set(x.get("nodes") or []) <= set(sn)}
    return out


def _divided_centerline(main_pts: list[LatLon], partner_pts: list[LatLon], lanes_sum: int, lane_w: float, step_ft: float = 40.0):
    """Centerline midway between two carriageways, plus [(index into the points, median width ft)]."""
    main_cl = Centerline(main_pts)
    partner_cl = Centerline(partner_pts, frame=main_cl.frame)
    n = max(1, int(main_cl.length // step_ft))
    mids, seps = [], []
    for k in range(n + 1):
        mp = main_cl.point(main_cl.length * k / n)
        ps, _ = partner_cl.project(mp)
        if not 0 <= ps <= partner_cl.length:
            continue  # beyond where the other carriageway runs alongside
        pp = partner_cl.point(ps)
        mids.append(_mid(mp, pp))
        # OSM draws each carriageway along its middle: median = separation minus half of each side's lanes
        seps.append(max(0.0, haversine_ft(mp, pp) - lanes_sum * lane_w / 2))
    return mids, seps


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
    oneway = _is_oneway(main.get("tags", {}))

    def straight_on(a: list[dict], b: list[dict]) -> bool:
        """a's last segment continues into b's first without doubling back (e.g. a U-turn onto
        the other carriageway of a divided road, which meets this one at the split)."""
        (p0, p1), (q0, q1) = a[-2:], b[:2]
        ax, ay = p1["lon"] - p0["lon"], p1["lat"] - p0["lat"]
        bx, by = q1["lon"] - q0["lon"], q1["lat"] - q0["lat"]
        na, nb = math.hypot(ax, ay), math.hypot(bx, by)
        return not (na and nb) or (ax * bx + ay * by) / (na * nb) > -0.3  # turn of less than ~107 degrees

    for _ in range(max_ways):
        grown = False
        for w in list(pool):
            wn, wg = w["nodes"], w["geometry"]
            if wn[0] == nodes[-1] and straight_on(geom, wg):
                nodes, geom = nodes + wn[1:], geom + wg[1:]
            elif wn[-1] == nodes[-1] and not oneway and straight_on(geom, wg[::-1]):
                nodes, geom = nodes + wn[-2::-1], geom + wg[-2::-1]
            elif wn[-1] == nodes[0] and straight_on(wg, geom):
                nodes, geom = wn[:-1] + nodes, wg[:-1] + geom
            elif wn[0] == nodes[0] and not oneway and straight_on(wg[::-1], geom):
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
    pts = _pts(geom)
    rclass = CLASS_MAP.get(tags.get("highway"), RoadClass.collector)
    one_way = _is_oneway(tags)
    lanes = _lanes(tags) or (1 if one_way else 2)
    lf = int(tags.get("lanes:forward", 0) or 0)
    lb = int(tags.get("lanes:backward", 0) or 0)
    if one_way:
        lf, lb = lanes, 0
    elif not (lf and lb):
        lf = max(1, lanes // 2)
        lb = max(1, lanes - lf)
    speed = _speed(tags)
    sources = {"centerline": "osm", "lanes": "osm" if "lanes" in tags else "rule_default", "road_class": "osm", "speed_mph": "osm" if speed else "rule_default"}

    # Divided road: pair the two one-way carriageways into one road with a median profile
    median: list[MedianPoint] = []
    route_nodes = list(node_ids)  # nodes whose crossings count as intersections
    lane_w = 12.0
    partner = _find_partner(main, Centerline(pts), node_ids, ways) if one_way else None
    if partner:
        p_nodes, p_geom = _stitch(partner, ways)
        p_tags = partner.get("tags", {})
        wide = rclass in (RoadClass.arterial, RoadClass.highway)
        lf = _lanes(tags) or (2 if wide else 1)
        lb = _lanes(p_tags) or (2 if wide else 1)
        sources["lanes"] = "osm" if "lanes" in tags and "lanes" in p_tags else "rule_default"
        mids, seps = _divided_centerline(pts, _pts(p_geom), lf + lb, lane_w)
        if len(mids) >= 2:
            # continue onto undivided stretches of the same street where the carriageways meet
            ends = {node_ids[0], node_ids[-1], p_nodes[0], p_nodes[-1]}
            used = {w["id"] for w in ways if set(w.get("nodes") or []) <= set(node_ids) | set(p_nodes)}
            before, after = [], []
            for e_nodes, g in _extend_undivided(ends, ways, tags.get("name", ""), used):
                ext = _pts(g)
                if haversine_ft(ext[0], mids[0]) <= haversine_ft(ext[0], mids[-1]):
                    before = ext[::-1]  # runs toward the start of the divided section
                else:
                    after = ext
                route_nodes += e_nodes
            pts = before + mids + after
            prof = [(len(before) + i, w) for i, w in enumerate(seps)]
            if before:
                prof.insert(0, (len(before) - 1, 0.0))
            if after:
                prof.append((len(before) + len(mids), 0.0))
            cum = Centerline(pts).cum
            median = [MedianPoint(station_ft=round(cum[i], 1), width_ft=round(w, 1)) for i, w in prof]
            route_nodes += p_nodes
            one_way = False
            sources["median"] = "osm"
    cl = Centerline(pts, median=[(m.station_ft, m.width_ft) for m in median])

    # Intersections: nodes of the main way shared with other drivable ways
    signals = {e["id"] for e in elements if e["type"] == "node" and e.get("tags", {}).get("highway") == "traffic_signals"}
    others: dict[int, str] = {}
    for e in elements:
        if e["type"] == "way" and e["id"] != main["id"] and e.get("tags", {}).get("highway") in DRIVABLE:
            nm = e.get("tags", {}).get("name", "")
            if nm and nm == tags.get("name"):
                continue
            for nid in e.get("nodes", []):
                others.setdefault(nid, nm)
    coords = {nid: LatLon(lat=g["lat"], lon=g["lon"]) for w in ways if len(w.get("nodes") or []) == len(w["geometry"]) for nid, g in zip(w["nodes"], w["geometry"])}
    ints = []
    for nid in dict.fromkeys(route_nodes):
        if nid in others and nid in coords:
            st, _ = cl.project(coords[nid])
            near = next((ix for ix in ints if ix.cross_street == others[nid] and abs(ix.station_ft - st) < 150), None)
            if near:  # a cross street meets both carriageways of a divided road: one intersection
                near.signalized = near.signalized or nid in signals
                continue
            ints.append(Intersection(station_ft=round(st, 1), cross_street=others[nid], signalized=nid in signals))
    # signals tagged on nodes near (not on) the way, e.g. at dual carriageways
    sig_nodes = [e for e in elements if e["type"] == "node" and e["id"] in signals and e["id"] not in route_nodes]
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
        lanes_forward=lf, lanes_backward=lb, lane_width_ft=lane_w, one_way=one_way, divided=bool(median) or tags.get("dual_carriageway") == "yes",
        median=median, road_class=rclass,
        has_bike_lane=any(k.startswith("cycleway") and v in ("lane", "track") for k, v in tags.items()),
        has_sidewalk=tags.get("sidewalk", "both") != "no",
        intersections=sorted(ints, key=lambda i: i.station_ft), sources=sources,
    )
    return road, {"schools": sorted(schools, key=lambda s: s["distance_ft"]), "osm_way_id": main["id"], "osm_partner_way_id": partner["id"] if partner else None, "highway": tags.get("highway")}


def lookup_road(lat: float, lon: float) -> tuple[RoadContext, dict]:
    return parse_overpass(_post(overpass_query(lat, lon)), lat, lon)


def geocode(q: str) -> list[dict]:
    try:
        r = httpx.get(NOMINATIM_URL, params={"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "us"}, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        return [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]
    except Exception as e:
        raise OSMUnavailable(str(e)) from e
