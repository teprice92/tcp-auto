"""HTTP API and static frontend.

Run: ``uvicorn tcp_auto.api.app:app --reload`` from ``backend/``.

Access control (v1): if ``TCP_ACCESS_KEY`` is set, every request needs that key, either as the
``tcp_key`` cookie (set by visiting ``/?key=...``) or an ``X-Access-Key`` header. Invite-only
email sign-in (see docs/PLAN.md §3.10) replaces this later.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import REPO_ROOT, RULES_DIR, __version__
from ..extract.keywords import extract_work_items, item_extent_ft
from ..geo import Centerline
from ..ingest.pdf import ingest_pdf, render_page_png
from ..models import Device, ExtractionResult, LatLon, Project, ProjectDetails, RoadContext, WorkItem
from ..pipeline import PlanInputError, build_plan, recheck
from ..rules import engine as rules_engine
from ..rules import proposals as rule_proposals
from ..rules.engine import resolve
from ..site import osm
from ..store.projects import ProjectStore

FRONTEND = Path(os.environ.get("TCP_FRONTEND_DIR") or REPO_ROOT / "frontend")
ACCESS_KEY = os.environ.get("TCP_ACCESS_KEY", "")
TILE_URL = os.environ.get("TCP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
TILE_ATTRIBUTION = os.environ.get("TCP_TILE_ATTRIBUTION", "&copy; OpenStreetMap contributors")
MAX_UPLOAD_MB = 40

app = FastAPI(title="FlagPole", version=__version__)
store = ProjectStore()


@app.middleware("http")
async def access_key(request: Request, call_next):
    if ACCESS_KEY:
        key = request.query_params.get("key")
        if key == ACCESS_KEY:
            resp = await call_next(request)
            resp.set_cookie("tcp_key", key, httponly=True, samesite="lax", max_age=30 * 86400)
            return resp
        if request.cookies.get("tcp_key") != ACCESS_KEY and request.headers.get("x-access-key") != ACCESS_KEY:
            return JSONResponse({"detail": "Access key required. Ask an admin for the link."}, status_code=401)
    return await call_next(request)


def _get(pid: str) -> Project:
    try:
        return store.get(pid)
    except KeyError:
        raise HTTPException(404, "Project not found")


def _safe_name(project: Project, ext: str) -> str:
    base = project.details.job_number or project.details.project_name or project.details.address or project.id
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"TCP_{base}")[:80] + ext


# ---------------------------------------------------------------------------
# Config / reference data
# ---------------------------------------------------------------------------


@app.get("/api/config")
def config() -> dict:
    def names(sub: str, skip=()):
        found = set()
        for root in (RULES_DIR, rules_engine.local_rules_dir()):
            found |= {p.stem for p in (root / sub).glob("*.yaml")}
        return sorted(n.replace("-", " ").title() for n in found if n not in skip)

    cities = names("cities/AZ", skip=("phoenix",))
    counties = names("counties/AZ")
    return {"version": __version__, "tile_url": TILE_URL, "tile_attribution": TILE_ATTRIBUTION, "cities": cities, "counties": counties}


@app.get("/api/rules/preview")
def rules_preview(city: str = "", county: str = "", road_owner: str = "city") -> dict:
    res = resolve(ProjectDetails(city=city, county=county, road_owner=road_owner))  # type: ignore[arg-type]
    return {
        "chain": res.chain,
        "statuses": res.statuses,
        "warnings": res.warnings,
        "peak_hours": res.get("peak_hours"),
        "police_triggers": [{"when": r.value.get("when"), "role": r.value.get("role"), "verified": r.verified, "cite": r.cite} for r in res.lists.get("police_required", [])],
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return store.list()


@app.post("/api/projects")
def create_project(details: ProjectDetails | None = Body(default=None)) -> Project:
    p = Project(details=details or ProjectDetails())
    return store.save(p, "created")


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> Project:
    return _get(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict:
    _get(pid)
    store.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/duplicate")
def duplicate_project(pid: str) -> Project:
    _get(pid)
    return store.duplicate(pid)


@app.put("/api/projects/{pid}")
def update_project(pid: str, payload: dict[str, Any] = Body(...)) -> Project:
    """Partial update: any of details, road, work_center, work_extent_ft, field_sources."""
    p = _get(pid)
    changed = []
    if "details" in payload:
        p.details = ProjectDetails.model_validate(payload["details"])
        changed.append("details")
    if "road" in payload:
        p.road = RoadContext.model_validate(payload["road"]) if payload["road"] else None
        changed.append("road")
    if "work_center" in payload:
        p.work_center = LatLon.model_validate(payload["work_center"]) if payload["work_center"] else None
        changed.append("work location")
    if "work_extent_ft" in payload:
        p.work_extent_ft = float(payload["work_extent_ft"] or 0)
    if "field_sources" in payload:
        p.field_sources.update(payload["field_sources"])
    return store.save(p, "updated " + ", ".join(changed) if changed else None)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


@app.post("/api/projects/{pid}/drawing")
async def upload_drawing(pid: str, file: UploadFile = File(...)) -> Project:
    p = _get(pid)
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF drawing.")
    path = store.drawing_path(pid)
    path.write_bytes(data)
    try:
        pages = ingest_pdf(path)
    except Exception as e:
        raise HTTPException(400, f"Could not read the PDF: {e}")
    result = extract_work_items(pages)
    p.extraction = result
    p.drawing_filename = file.filename
    # Pre-fill details from the drawing where empty (with source badges)
    if result.title_block.job_number and not p.details.job_number:
        p.details.job_number = result.title_block.job_number
        p.field_sources["job_number"] = "drawing"
    if result.title_block.address and not p.details.address:
        p.details.address = result.title_block.address
        p.field_sources["address"] = "drawing"
    _update_extent(p)
    return store.save(p, f"uploaded drawing {file.filename} ({len(result.items)} work items found)")


def _update_extent(p: Project) -> None:
    if p.extraction and p.extraction.pages:
        page = next((pg for pg in p.extraction.pages if any(i.page == pg.page for i in p.extraction.items)), p.extraction.pages[0])
        p.work_extent_ft = item_extent_ft(p.extraction.items, page)


@app.get("/api/projects/{pid}/drawing/page/{n}.png")
def drawing_page(pid: str, n: int) -> Response:
    _get(pid)
    path = store.drawing_path(pid)
    if not path.exists():
        raise HTTPException(404, "No drawing uploaded")
    return Response(render_page_png(path, n), media_type="image/png")


@app.put("/api/projects/{pid}/items")
def update_items(pid: str, items: list[WorkItem] = Body(...)) -> Project:
    p = _get(pid)
    if not p.extraction:
        p.extraction = ExtractionResult(pages=[], items=[])
    p.extraction.items = items
    _update_extent(p)
    return store.save(p, f"edited work items ({sum(i.included for i in items)} included)")


# ---------------------------------------------------------------------------
# Map lookups (optional; need outbound network)
# ---------------------------------------------------------------------------


@app.get("/api/road/lookup")
def road_lookup(lat: float, lon: float) -> dict:
    try:
        road, extra = osm.lookup_road(lat, lon)
    except osm.OSMUnavailable as e:
        raise HTTPException(503, f"Map data service unavailable: {e}. Draw the road and enter lanes/speed manually.")
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"road": road.model_dump(), **extra}


@app.get("/api/geocode")
def geocode(q: str) -> list[dict]:
    try:
        return osm.geocode(q + ", Arizona")
    except osm.OSMUnavailable as e:
        raise HTTPException(503, f"Geocoder unavailable: {e}")


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@app.post("/api/projects/{pid}/generate")
def generate_plan(pid: str) -> Project:
    p = _get(pid)
    try:
        p.plan, _, _ = build_plan(p)
    except PlanInputError as e:
        raise HTTPException(400, str(e))
    return store.save(p, f"generated plan ({p.plan.template}, {len(p.plan.devices)} devices)")


@app.put("/api/projects/{pid}/plan/devices")
def update_devices(pid: str, devices: list[Device] = Body(...)) -> Project:
    p = _get(pid)
    if not p.plan or not p.road:
        raise HTTPException(400, "Generate a plan first")
    old = {d.id: d for d in p.plan.devices}
    for d in devices:
        prev = old.get(d.id)
        if prev is None or (abs(prev.lat - d.lat) > 1e-9 or abs(prev.lon - d.lon) > 1e-9):
            d.origin = "manual"
    cl = Centerline(p.road.centerline)
    for d in devices:
        if d.origin == "manual":
            st, _ = cl.project(LatLon(lat=d.lat, lon=d.lon))
            bearing = cl.bearing_deg(st)
            d.rotation_deg = (bearing + 180) % 360 if d.direction == "backward" else bearing
    p.plan.devices = devices
    p.plan.version += 1
    recheck(p)
    return store.save(p, f"edited plan (v{p.plan.version})")


# ---------------------------------------------------------------------------
# Report / email
# ---------------------------------------------------------------------------


@app.get("/api/projects/{pid}/report.html", response_class=HTMLResponse)
def report_html(pid: str) -> str:
    from ..report.render import render_html

    p = _get(pid)
    if not p.plan:
        raise HTTPException(400, "Generate a plan first")
    return render_html(p)


@app.get("/api/projects/{pid}/report.pdf")
def report_pdf(pid: str) -> Response:
    from ..report.render import render_pdf

    p = _get(pid)
    if not p.plan:
        raise HTTPException(400, "Generate a plan first")
    pdf = render_pdf(p)
    name = _safe_name(p, ".pdf")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/projects/{pid}/email.eml")
def report_email(pid: str, to: str | None = None) -> Response:
    from ..email.eml import build_eml
    from ..report.render import render_pdf

    p = _get(pid)
    if not p.plan:
        raise HTTPException(400, "Generate a plan first")
    pdf = render_pdf(p)
    eml = build_eml(p, pdf, _safe_name(p, ".pdf"), to=to)
    return Response(eml, media_type="message/rfc822", headers={"Content-Disposition": f'attachment; filename="{_safe_name(p, ".eml")}"'})


@app.get("/api/projects/{pid}/checklist.html", response_class=HTMLResponse)
def checklist_html(pid: str) -> str:
    from ..report.render import render_checklist_html

    p = _get(pid)
    if not p.plan:
        raise HTTPException(400, "Generate a plan first")
    return render_checklist_html(p)


@app.get("/api/projects/{pid}/checklist.pdf")
def checklist_pdf(pid: str) -> Response:
    from ..report.render import render_checklist_pdf

    p = _get(pid)
    if not p.plan:
        raise HTTPException(400, "Generate a plan first")
    name = _safe_name(p, "").replace("TCP_", "Checklist_") + ".pdf"
    return Response(render_checklist_pdf(p), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/projects/{pid}/checklist")
def checklist_json(pid: str) -> list[dict]:
    from dataclasses import asdict

    from ..report.checklist import build_checklist

    p = _get(pid)
    if not p.plan:
        return []
    return [asdict(s) for s in build_checklist(p)]


# ---------------------------------------------------------------------------
# Rules library, proposals, review
# ---------------------------------------------------------------------------


def _rules_error(e: Exception) -> HTTPException:
    if isinstance(e, KeyError):
        return HTTPException(404, "Proposal not found")
    return HTTPException(400, str(e))


@app.get("/api/rules/layers")
def rules_layers() -> list[dict]:
    return rule_proposals.list_layers()


@app.get("/api/rules/layer")
def rules_layer(id: str) -> dict:
    try:
        return rule_proposals.layer_rules(id)
    except FileNotFoundError:
        raise HTTPException(404, "Unknown rules layer")


@app.get("/api/rules/keys")
def rules_keys() -> list[dict]:
    from ..rules.assistant import rule_keys
    from ..rules.schema import CONDITIONS

    return [{**k, "conditions": CONDITIONS} for k in rule_keys()]


@app.get("/api/rules/proposals")
def rules_proposals(status: str | None = None) -> list[dict]:
    return [p.model_dump(mode="json", exclude={"source_text"}) for p in rule_proposals.list_all(status)]


@app.get("/api/rules/proposals/{pid}")
def rules_proposal(pid: str) -> rule_proposals.RuleProposal:
    try:
        return rule_proposals.get(pid)
    except Exception as e:
        raise _rules_error(e)


@app.post("/api/rules/proposals")
def rules_propose(p: rule_proposals.RuleProposal) -> rule_proposals.RuleProposal:
    """Manual proposal (no AI). Still goes to review."""
    p.origin, p.status, p.model = "manual", "pending", None
    try:
        return rule_proposals.create(p)
    except Exception as e:
        raise _rules_error(e)


@app.post("/api/rules/proposals/draft")
def rules_draft(payload: dict[str, Any] = Body(...)) -> rule_proposals.RuleProposal:
    """AI-assisted proposal from pasted text. Needs an API key."""
    from ..rules.assistant import AssistantError, draft

    new = payload.get("new_layer")
    try:
        return draft(
            layer_id=payload.get("layer_id", ""), new_layer=rule_proposals.NewLayer(**new) if new else None,
            source_title=payload.get("source_title", ""), source_url=payload.get("source_url", ""),
            text=payload.get("text", ""), author=payload.get("author", ""),
        )
    except AssistantError as e:
        raise HTTPException(e.status, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/rules/proposals/{pid}")
def rules_edit(pid: str, changes: list[rule_proposals.RuleChange] = Body(...)) -> rule_proposals.RuleProposal:
    try:
        p = rule_proposals.get(pid)
        if p.status != "pending":
            raise ValueError(f"Proposal is already {p.status}.")
        p.changes = changes
        return rule_proposals.save(rule_proposals.validate(p))
    except Exception as e:
        raise _rules_error(e)


@app.post("/api/rules/proposals/{pid}/accept")
def rules_accept(pid: str, payload: dict[str, Any] = Body(...)) -> rule_proposals.RuleProposal:
    try:
        return rule_proposals.accept(pid, payload.get("reviewer", ""), bool(payload.get("verified")), payload.get("note", ""))
    except Exception as e:
        raise _rules_error(e)


@app.post("/api/rules/proposals/{pid}/reject")
def rules_reject(pid: str, payload: dict[str, Any] = Body(...)) -> rule_proposals.RuleProposal:
    try:
        return rule_proposals.reject(pid, payload.get("reviewer", ""), payload.get("note", ""))
    except Exception as e:
        raise _rules_error(e)


@app.get("/api/settings/ai")
def ai_settings() -> dict:
    from ..rules.assistant import settings_status

    return settings_status()


@app.put("/api/settings/ai")
def ai_settings_update(payload: dict[str, Any] = Body(...)) -> dict:
    from ..rules.assistant import save_settings

    return save_settings(api_key=payload.get("api_key"), model=payload.get("model"), clear_key=bool(payload.get("clear_key")))


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")
