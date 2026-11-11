import email
import os

import pytest
from fastapi.testclient import TestClient

from tcp_auto.email.eml import build_eml
from tcp_auto.pipeline import build_plan
from tcp_auto.report.render import render_html


def test_report_html_has_core_sections(make_project):
    p = make_project(description="replace two poles")
    p.plan, _, _ = build_plan(p)
    h = render_html(p)
    for s in ["Traffic Control Plan", "What is happening", "Timeline", "replace two poles", "<svg", "Submitted for agency review",
              "Traffic control provided", "Standards followed"]:
        assert s in h
    # internal to-dos stay off the agency submittal
    for s in ["confirm with agency", "Requirements &amp; checklist", "Review notes", "Submit the TCP at least"]:
        assert s not in h


def test_checklist_has_gotchas(make_project):
    from tcp_auto.report.checklist import build_checklist
    from tcp_auto.report.render import render_checklist_html

    p = make_project(school_zone=True)
    p.road.speed_confirmed = False
    p.plan, _, _ = build_plan(p)
    sections = {s.title: s for s in build_checklist(p)}
    before = " ".join(i.text for i in sections["Before you submit"].items)
    assert "qualified person" in before and "posted speed" in before and "3 full working days" in before
    bookings = sections["Bookings & scheduling"].items
    assert any("Book a police officer" in i.text and i.tag == "confirm with agency" for i in bookings)
    assert any("07:00-08:30" in i.text for i in bookings)
    h = render_checklist_html(p)
    assert "do not submit to the agency" in h


def test_eml_is_unsent_draft_with_pdf(make_project):
    p = make_project()
    p.plan, _, _ = build_plan(p)
    raw = build_eml(p, b"%PDF-1.4 test", "tcp.pdf", to="permits@example.gov")
    msg = email.message_from_bytes(raw)
    assert msg["X-Unsent"] == "1" and msg["To"] == "permits@example.gov"
    att = [part for part in msg.walk() if part.get_filename() == "tcp.pdf"]
    assert att and att[0].get_payload(decode=True).startswith(b"%PDF")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_DATA_DIR", str(tmp_path))
    import importlib

    import tcp_auto.api.app as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_api_end_to_end(client, sample_pdf):
    p = client.post("/api/projects", json={"project_name": "Test", "city": "Tempe"}).json()
    pid = p["id"]
    with open(sample_pdf, "rb") as f:
        r = client.post(f"/api/projects/{pid}/drawing", files={"file": ("d.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["extraction"]["items"]) == 5
    assert body["details"]["job_number"] == "7654321" and body["field_sources"]["job_number"] == "drawing"

    road = {"name": "E University Dr", "centerline": [{"lat": 33.4215, "lon": -111.92}, {"lat": 33.4215, "lon": -111.905}],
            "speed_mph": 40, "speed_confirmed": True, "lanes_forward": 2, "lanes_backward": 2, "road_class": "arterial"}
    details = body["details"] | {"phases": [{"name": "Work", "start_date": "2026-12-01", "end_date": "2026-12-02", "start_time": "09:00", "end_time": "15:00"}]}
    r = client.put(f"/api/projects/{pid}", json={"road": road, "work_center": {"lat": 33.4215, "lon": -111.9125}, "details": details})
    assert r.status_code == 200
    r = client.post(f"/api/projects/{pid}/generate")
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert plan["template"] == "lane_closure_multilane"

    devices = plan["devices"]
    devices[0]["lat"] += 0.0001
    r = client.put(f"/api/projects/{pid}/plan/devices", json=devices)
    assert r.status_code == 200 and r.json()["plan"]["version"] == 2
    assert r.json()["plan"]["devices"][0]["origin"] == "manual"

    assert client.get(f"/api/projects/{pid}/report.html").status_code == 200
    assert client.get(f"/api/projects/{pid}/drawing/page/0.png").headers["content-type"] == "image/png"
    assert any(x["id"] == pid for x in client.get("/api/projects").json())
    dup = client.post(f"/api/projects/{pid}/duplicate").json()
    assert dup["id"] != pid and dup["plan"]


def test_generate_without_road_is_400(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    assert client.post(f"/api/projects/{pid}/generate").status_code == 400


@pytest.mark.skipif(os.environ.get("TCP_SKIP_PDF") == "1", reason="no browser")
def test_pdf_render(make_project):
    from tcp_auto.report.render import render_pdf

    p = make_project()
    p.plan, _, _ = build_plan(p)
    pdf = render_pdf(p)
    assert pdf.startswith(b"%PDF") and len(pdf) > 10000
