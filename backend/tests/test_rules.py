from tcp_auto.models import ProjectDetails
from tcp_auto.rules.engine import Facts, evaluate, resolve


def facts(**kw):
    base = dict(road_class="arterial", speed_mph=40, lane_closure=True, through_lanes_remaining=1)
    base.update(kw)
    return Facts(**base)


def test_tempe_chain_includes_phoenix_and_peak_hours():
    r = resolve(ProjectDetails(city="Tempe"))
    assert r.chain == ["federal/mutcd-11", "states/AZ", "cities/AZ/phoenix", "cities/AZ/tempe"]
    assert r.get("peak_hours")["weekdays"] == ["07:00-08:30", "15:30-18:30"]
    # ADOT practice is used as a reference for night work when the chain doesn't define it
    assert "reference" in r.rule("device_spacing").layer


def test_gilbert_signal_within_300ft_requires_police():
    r = resolve(ProjectDetails(city="Gilbert"))
    reqs = evaluate(r, facts(min_signal_distance_ft=250))
    police = [q for q in reqs if q.kind == "police" and q.required]
    assert police and "300 ft" in police[0].text and police[0].verified
    assert not [q for q in evaluate(r, facts(min_signal_distance_ft=450)) if q.kind == "police" and q.required]


def test_school_zone_police_is_applied_but_unverified():
    for city in ["Tempe", "Gilbert", "Mesa", "Chandler", "Queen Creek", "Apache Junction"]:
        reqs = evaluate(resolve(ProjectDetails(city=city)), facts(school_zone=True))
        school = [q for q in reqs if q.kind == "police" and q.required and "school" in q.text]
        assert school, city
        assert not school[0].verified


def test_advisory_triggers_are_not_required():
    reqs = evaluate(resolve(ProjectDetails(city="Tempe")), facts())
    adv = [q for q in reqs if q.kind == "police" and not q.required]
    assert adv


def test_gilbert_arrowboard_on_arterial_lane_closure():
    reqs = evaluate(resolve(ProjectDetails(city="Gilbert")), facts())
    assert any(q.kind == "device" and "arrowboard" in q.text for q in reqs)
    reqs = evaluate(resolve(ProjectDetails(city="Gilbert")), facts(road_class="local"))
    assert not any(q.kind == "device" and "arrowboard" in q.text for q in reqs)


def test_missing_city_warns():
    r = resolve(ProjectDetails(city="Scottsdale"))
    assert any("Local rules not loaded" in w for w in r.warnings)
    assert r.chain == ["federal/mutcd-11", "states/AZ"]


def test_tribal_and_adot():
    assert any("tribal" in w.lower() for w in resolve(ProjectDetails(road_owner="tribal")).warnings)
    r = resolve(ProjectDetails(road_owner="ADOT"))
    assert "states/AZ-adot" in r.chain
