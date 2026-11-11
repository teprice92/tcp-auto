import json
from types import SimpleNamespace

import pytest

from tcp_auto.models import ProjectDetails
from tcp_auto.rules import engine, proposals
from tcp_auto.rules.engine import Facts, evaluate, resolve
from tcp_auto.rules.proposals import NewLayer, RuleChange, RuleCite, RuleProposal
from tcp_auto.rules.schema import check_value, norm_window


@pytest.fixture(autouse=True)
def local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    engine.invalidate_cache()
    yield tmp_path
    engine.invalidate_cache()


def facts(**kw):
    base = dict(road_class="arterial", speed_mph=40, lane_closure=True, through_lanes_remaining=1)
    base.update(kw)
    return Facts(**base)


def test_time_normalization():
    assert norm_window("7:00 a.m. to 8:30 a.m.") == "07:00-08:30"
    assert norm_window("3:30 pm - 6:30 pm") == "15:30-18:30"
    r = check_value("peak_hours", {"road_class": ["Arterials"], "weekdays": ["6:30 am-8:30 am"]})
    assert not r.errors and r.value["road_class"] == ["arterial"] and r.value["weekdays"] == ["06:30-08:30"]
    assert check_value("peak_hours", {"weekdays": ["sometime"]}).errors
    assert check_value("police_required", {"when": {"near_a_school": True}, "role": "officer"}).warnings


def test_proposal_requires_review_then_applies():
    p = proposals.create(RuleProposal(layer_id="cities/AZ/mesa", source_title="Mesa TTC Manual 2nd Ed", changes=[
        RuleChange(op="add_item", key="police_required", value={"when": {"within_ft_of_signalized_intersection": 150}, "role": "off-duty Mesa officer"},
                   cite=RuleCite(section="4.2"), quote="An off-duty officer is required within 150 feet of a signal."),
        RuleChange(op="set", key="peak_hours", value={"road_class": ["arterial"], "weekdays": ["6:00 am - 9:00 am"]}, cite=RuleCite(section="3.1")),
    ]))
    assert p.status == "pending"
    # Not applied before acceptance
    assert not evaluate(resolve(ProjectDetails(city="Mesa")), facts(min_signal_distance_ft=100)) or \
        not any("150" in r.text for r in evaluate(resolve(ProjectDetails(city="Mesa")), facts(min_signal_distance_ft=100)))
    with pytest.raises(ValueError):
        proposals.accept(p.id, reviewer="", verified=True)
    proposals.accept(p.id, reviewer="J. Engineer", verified=True)
    res = resolve(ProjectDetails(city="Mesa"))
    reqs = evaluate(res, facts(min_signal_distance_ft=100))
    hit = [r for r in reqs if r.kind == "police" and r.required and "150 ft" in r.text]
    assert hit and hit[0].verified and "Mesa TTC Manual 2nd Ed, 4.2" in hit[0].citation
    assert res.get("peak_hours")["weekdays"] == ["06:00-09:00"]
    # existing Mesa triggers (school zone) are kept
    assert any("school" in r.text for r in evaluate(res, facts(school_zone=True)) if r.kind == "police")
    assert proposals.get(p.id).status == "accepted"


def test_verified_trigger_replaces_unverified_placeholder():
    p = proposals.create(RuleProposal(layer_id="cities/AZ/gilbert", source_title="Gilbert TCM", changes=[
        RuleChange(op="add_item", key="police_required", value={"when": {"school_zone": True, "during": "school_hours"}, "role": "extra-duty Gilbert officer"},
                   cite=RuleCite(section="6.3"))]))
    proposals.accept(p.id, reviewer="R", verified=True)
    school = [r for r in evaluate(resolve(ProjectDetails(city="Gilbert")), facts(school_zone=True)) if r.kind == "police" and "school" in r.text]
    assert len(school) == 1 and school[0].verified and "Gilbert TCM, 6.3" in school[0].citation


def test_invalid_proposal_cannot_be_accepted():
    p = proposals.create(RuleProposal(layer_id="cities/AZ/tempe", source_title="Doc", changes=[
        RuleChange(key="peak_hours", value={"weekdays": ["whenever"]})]))
    assert p.changes[0].errors
    with pytest.raises(ValueError):
        proposals.accept(p.id, reviewer="R", verified=False)


def test_new_city_layer():
    p = proposals.create(RuleProposal(layer_id="", new_layer=NewLayer(level="city", name="Scottsdale"), source_title="Scottsdale ROW manual",
                                      changes=[RuleChange(key="peak_hours", value={"road_class": ["arterial"], "weekdays": ["07:00-09:00"]}, cite=RuleCite(section="2"))]))
    assert p.layer_id == "cities/AZ/scottsdale"
    proposals.accept(p.id, reviewer="R", verified=False)
    res = resolve(ProjectDetails(city="Scottsdale"))
    assert "cities/AZ/scottsdale" in res.chain and res.rule("peak_hours").verified is False
    assert not any("Local rules not loaded" in w for w in res.warnings)


def test_reject():
    p = proposals.create(RuleProposal(layer_id="states/AZ", source_title="x", changes=[RuleChange(key="note", value="hi", cite=RuleCite(section="1"))]))
    proposals.reject(p.id, reviewer="R", note="not real")
    assert proposals.get(p.id).status == "rejected"
    with pytest.raises(ValueError):
        proposals.accept(p.id, reviewer="R", verified=True)


class FakeClient:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.calls = payload, stop, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def test_ai_draft_goes_to_review():
    from tcp_auto.rules.assistant import draft

    client = FakeClient({"summary": "Officer near signals.", "questions": ["Applies to collectors?"], "changes": [
        {"op": "add_item", "key": "police_required", "value_json": json.dumps({"when": {"within_ft_of_signalized_intersection": 200}, "role": "off-duty officer"}),
         "section": "5.1", "quote": "within 200 feet of any signalized intersection", "note": "", "confidence": "high"}]})
    p = draft("cities/AZ/chandler", None, "Chandler EDSM Ch. 7", "", "An off-duty officer is required within 200 feet of any signalized intersection.", client=client)
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert p.status == "pending" and p.origin == "ai" and p.changes[0].value["when"]["within_ft_of_signalized_intersection"] == 200
    assert p.questions == ["Applies to collectors?"]


def test_ai_refusal_and_missing_key():
    from tcp_auto.rules.assistant import AssistantError, draft

    with pytest.raises(AssistantError) as e:
        draft("states/AZ", None, "x", "", "text", client=FakeClient({}, stop="refusal"))
    assert e.value.status == 422
    with pytest.raises(AssistantError) as e:
        draft("states/AZ", None, "x", "", "text")
    assert e.value.status == 400 and "API key" in str(e.value)


def test_settings_hide_key():
    from tcp_auto.rules.assistant import save_settings, settings_status

    st = save_settings(api_key="sk-ant-test-1234")
    assert st["configured"] and st["key_hint"] == "…1234" and "sk-ant" not in json.dumps(st)
    assert not save_settings(clear_key=True)["configured"]
