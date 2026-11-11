"""Build the static FlagPole online demo (GitHub Pages or any static host).

    python packaging/build_demo.py site/            # GitHub Pages / any static host
    python packaging/build_demo.py site/ --embed    # for embedded viewers (e.g. a Claude artifact)

Runs the real backend in-process to create sample projects, then saves everything the editor needs
(API responses, report/checklist HTML and PDFs, email draft, drawing image) as static files.
frontend/demo.js replays them in the browser. PDFs are made with an installed Chrome/Edge;
if none is found they're skipped and the HTML previews still work.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CONTACTS = {
    "preparer": "Demo Designer", "preparer_phone": "480-555-0100", "field_supervisor": "Demo Foreman", "field_supervisor_phone": "480-555-0101",
    "emergency_contact": "Utility Dispatch", "emergency_phone": "480-555-0199", "traffic_control_company": "Demo Barricade Co.",
}


def phases(start, end, a="09:00", b="15:00"):
    return [{"name": "Work", "start_date": start, "end_date": end, "start_time": a, "end_time": b}]


SAMPLES = [
    dict(name="Demo 1 – Pole replacement from drawing (Tempe)", drawing=True,
         details={"city": "Tempe", "work_position": "lane", "phases": phases("2026-12-01", "2026-12-02"), "contacts": CONTACTS, "permit_number": "ROW-DEMO-001"},
         road={"name": "E University Dr", "centerline": [{"lat": 33.4216, "lon": -111.9200}, {"lat": 33.4216, "lon": -111.9050}], "speed_mph": 40, "speed_confirmed": True,
               "lanes_forward": 2, "lanes_backward": 2, "road_class": "arterial", "intersections": [{"station_ft": 1400, "cross_street": "S Rural Rd", "signalized": True}]},
         center={"lat": 33.4216, "lon": -111.9125}),
    dict(name="Demo 2 – Near a signal, police required (Gilbert)", drawing=False,
         details={"city": "Gilbert", "address": "E Guadalupe Rd at S Gilbert Rd", "description": "replace a pad-mount transformer", "work_position": "lane",
                  "phases": phases("2026-12-03", "2026-12-04"), "contacts": CONTACTS, "permit_number": "TRF-DEMO-002", "job_number": "WO-DEMO-2"},
         road={"name": "E Guadalupe Rd", "centerline": [{"lat": 33.3636, "lon": -111.8020}, {"lat": 33.3636, "lon": -111.7820}], "speed_mph": 45, "speed_confirmed": True,
               "lanes_forward": 2, "lanes_backward": 2, "road_class": "arterial", "intersections": [{"station_ft": 3190, "cross_street": "S Gilbert Rd", "signalized": True}]},
         center={"lat": 33.3636, "lon": -111.7905}),
    dict(name="Demo 3 – Night transfer, two-lane road (Gilbert)", drawing=False,
         details={"city": "Gilbert", "address": "E Elliot Rd", "description": "transfer conductors to new poles", "work_position": "lane",
                  "phases": phases("2026-12-08", "2026-12-08", "20:00", "23:30"), "contacts": CONTACTS, "job_number": "WO-DEMO-3"},
         road={"name": "E Elliot Rd", "centerline": [{"lat": 33.3497, "lon": -111.7520}, {"lat": 33.3497, "lon": -111.7400}], "speed_mph": 35, "speed_confirmed": True,
               "lanes_forward": 1, "lanes_backward": 1, "road_class": "collector", "has_sidewalk": True},
         center={"lat": 33.3497, "lon": -111.7460}),
]


def main(out: Path, embed: bool = False) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="flagpole-demo-"))
    os.environ["TCP_DATA_DIR"] = str(tmp)
    from fastapi.testclient import TestClient

    from tcp_auto.api.app import app

    c = TestClient(app)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "frontend", out)
    (out / "demo").mkdir()

    data = {"projects": {}, "originals": {}, "files": {}, "checklists": {}, "rules_preview": {}, "rules_layer": {}}
    pdf_ok = True
    for s in SAMPLES:
        p = c.post("/api/projects", json={"project_name": s["name"], **s["details"]}).json()
        pid = p["id"]
        if s["drawing"]:
            with open(ROOT / "samples" / "sample_drawing.pdf", "rb") as f:
                p = c.post(f"/api/projects/{pid}/drawing", files={"file": ("sample_drawing.pdf", f, "application/pdf")}).json()
        r = c.put(f"/api/projects/{pid}", json={"details": {**p["details"], **s["details"]}, "road": s["road"], "work_center": s["center"]})
        r.raise_for_status()
        p = c.post(f"/api/projects/{pid}/generate").json()
        data["projects"][pid] = p
        data["originals"][pid] = p["plan"]
        data["checklists"][pid] = c.get(f"/api/projects/{pid}/checklist").json()
        d = out / "demo" / pid
        d.mkdir()
        files = {}
        for name, url in [("report_html", "report.html"), ("checklist_html", "checklist.html")]:
            (d / url).write_text(c.get(f"/api/projects/{pid}/{url}").text, encoding="utf-8")
            files[name] = f"demo/{pid}/{url}"
        if pdf_ok:
            try:
                for name, url in [("report_pdf", "report.pdf"), ("checklist_pdf", "checklist.pdf"), ("email_eml", "email.eml")]:
                    r = c.get(f"/api/projects/{pid}/{url}")
                    r.raise_for_status()
                    (d / url).write_bytes(r.content)
                    files[name] = f"demo/{pid}/{url}"
            except Exception as e:  # no browser for PDFs on this machine
                print(f"  (skipping PDFs: {e})")
                pdf_ok = False
        if p.get("extraction"):
            (d / "page0.png").write_bytes(c.get(f"/api/projects/{pid}/drawing/page/0.png").content)
            files["page0"] = f"demo/{pid}/page0.png"
        data["files"][pid] = files
        print(f"  {s['name']}: {p['plan']['template']}, {len(p['plan']['devices'])} devices")

    data["blank_project"] = {k: v for k, v in c.post("/api/projects", json={}).json().items() if k != "id"}
    data["config"] = c.get("/api/config").json()
    data["rules_layers"] = c.get("/api/rules/layers").json()
    for layer in data["rules_layers"]:
        data["rules_layer"][layer["id"]] = c.get("/api/rules/layer", params={"id": layer["id"]}).json()
    data["rule_keys"] = c.get("/api/rules/keys").json()
    data["ai_settings"] = c.get("/api/settings/ai").json()
    combos = [("city", city, "") for city in [""] + data["config"]["cities"]] + [("county", "", co) for co in [""] + data["config"]["counties"]]
    combos += [("ADOT", "", ""), ("tribal", "", ""), ("unknown", "", "")]
    for owner, city, county in combos:
        data["rules_preview"][f"{owner}|{city}|{county}"] = c.get("/api/rules/preview", params={"road_owner": owner, "city": city, "county": county}).json()
    # Stable ids so rebuilt sites have the same file paths (clean republishing)
    text = json.dumps(data)
    for i, pid in enumerate(list(data["projects"]), start=1):
        fixed = f"de{i:010d}"
        text = text.replace(pid, fixed)
        (out / "demo" / pid).rename(out / "demo" / fixed)
    (out / "demo" / "data.json").write_text(text, encoding="utf-8")

    # index.html: relative paths (works under any sub-path, e.g. user.github.io/repo/) and load the demo shim first
    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/", "")
    html = html.replace('<script src="vendor/leaflet/leaflet.js"></script>', '<script src="vendor/leaflet/leaflet.js"></script>\n<script src="demo.js"></script>')
    html = html.replace("<title>FlagPole – Traffic control plans</title>", "<title>FlagPole Demo</title>")
    html = html.replace('<a class="brand" href="/"', '<a class="brand" href="#"' if embed else '<a class="brand" href="./"')
    if embed:
        # Embedded viewers wrap the page in their own document shell and block pop-ups/downloads.
        html = html.replace('<script src="demo.js"></script>', '<script>window.FP_EMBED = true;</script>\n<script src="demo.js"></script>')
        for tag in ("<!doctype html>", '<html lang="en">', "<head>", "</head>", "<body>", "</body>", "</html>",
                    '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">'):
            html = html.replace(tag + "\n", "").replace(tag, "")
    (out / "index.html").write_text(html, encoding="utf-8")
    css = (out / "style.css").read_text(encoding="utf-8")
    css += """
/* online demo banner */
.demo-banner { display: flex; align-items: center; gap: 10px; justify-content: center; background: #ff7a1a; color: #fff; font-size: 13px; padding: 6px 12px; }
.demo-banner button { min-height: 24px; padding: 0 8px; background: #ffffff33; color: #fff; border-color: #ffffff66; flex: none; }
@media (max-width: 820px) { .demo-banner .long { display: none; } .demo-banner { font-size: 12px; padding: 4px 10px; } }
.demo-doc { position: fixed; inset: 0; z-index: 3000; background: var(--bg); display: flex; flex-direction: column; }
.demo-doc-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; background: var(--blue-900); color: #fff; }
.demo-doc-bar button { background: #ffffff1f; color: #fff; border-color: #ffffff40; }
.demo-doc iframe { flex: 1; width: 100%; border: 0; background: #fff; }
"""
    (out / "style.css").write_text(css, encoding="utf-8")
    for junk in out.rglob("__pycache__"):
        shutil.rmtree(junk)
    (out / ".nojekyll").write_text("")
    shutil.rmtree(tmp, ignore_errors=True)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Demo site written to {out} ({size / 1e6:.1f} MB). Serve it with any static host, e.g. `python -m http.server -d {out}`.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(Path(args[0] if args else "site").resolve(), embed="--embed" in sys.argv)
