<img src="frontend/logo.svg" width="72" alt="FlagPole logo">

# FlagPole

**Traffic control plans from pole sheets.** FlagPole drafts Traffic Control Plans (TCPs) from
electrical utility design drawings. (The code package is still named `tcp_auto`.)

Upload a PDF drawing where work is labeled **Construct** / **Remove**. Then confirm the road on a
map and enter the details the drawing doesn't have. FlagPole lays out a draft plan (signs, taper,
buffer, cones/drums, arrow board, flaggers, police officer, trucks) using the MUTCD plus Arizona and
East Valley city rules. Adjust it by drag-and-drop, then download a short PDF report (map,
explanation, timeline) or an Outlook email draft to send to the city or county.

> Generated plans are **drafts**. They must be reviewed and approved by qualified personnel before use.

- Plan and design decisions: [docs/PLAN.md](docs/PLAN.md)
- What each city's rules say, with citations: [docs/jurisdiction-research.md](docs/jurisdiction-research.md)
- Rule files and the source document register: [rules/](rules/README.md)

## Status (v0.1, first working slice)

| Area | State |
|---|---|
| PDF ingestion + "Construct"/"Remove" extraction, scale detection, title block (job #, address) | Working (vector PDFs; scanned PDFs need manual items) |
| Project details form, timeline phases | Working |
| Road: draw centerline, set work location, lanes/speed/class, intersections | Working |
| OSM road lookup (lanes, speed, signals, nearby schools) and address search | Implemented; needs internet access to Overpass/Nominatim |
| Rules engine: federal → Arizona → (Phoenix TBM) → city; police/device triggers with citations | Working (Tempe, Gilbert, Queen Creek partial; Mesa, Chandler, Apache Jct. stubs) |
| Layout templates: shoulder, two-lane with flaggers, multi-lane lane closure | Working |
| Intersections | Detected; police triggers (e.g., Gilbert 300 ft from a signal); cross-street sign placeholders. Dedicated near/far-side templates not yet |
| Night work | Detected from sunset/sunrise and city rules; drums, lit signs, light towers |
| Drag-and-drop editor with live compliance checks | Working |
| Report (PDF) and email draft (.eml for Outlook) | Working |
| LLM assistant | Not yet (placeholder in plan) |
| Sign-in | Optional shared access key (`TCP_ACCESS_KEY`); invite-only sign-in planned |

## Brand

- **Name:** FlagPole. The utility pole is the work; the flagger's flag is the traffic control.
- **Logo:** `frontend/logo.svg`. A white utility pole with an orange flag and cone on a blue tile. Works down to 16 px (also used as the favicon).
- **Colors:** blue is the interface (primary `#0a5cad`, navy `#0b2545`, bright `#1f7ae0`, tint `#eef5fd`).
  **Orange is reserved for work-zone devices** (cones, signs, work area) so it never competes with buttons on the map.
  This is an original palette in the spirit of Arizona utilities' blues. It doesn't copy any company's branding.
- Design tokens live at the top of `frontend/style.css`. The report uses the same palette (`backend/tcp_auto/report/templates/report.html`).

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e "backend[dev]"
python -m playwright install chromium      # for PDF reports (skip if Chromium is already available)
cd backend && uvicorn tcp_auto.api.app:app --reload
# open http://localhost:8000
```

Try it with the synthetic sample drawing in `samples/sample_drawing.pdf` (regenerate it with
`python samples/make_sample_drawing.py samples/sample_drawing.pdf`).

**Workflow in the app:**
1. **Drawing:** upload the PDF and check the found items.
2. **Details:** pick the city and road owner, describe the work, and set the timeline and contacts.
3. **Road:** use "Set work location", then "Draw road centerline" (or "Look up road (OSM)"). Confirm the speed and lanes, and add intersections.
4. **Plan:** generate the plan, then drag devices, add or delete them, and watch the checks.
5. **Report:** preview it, download the PDF, or download an email draft.

## Tests

```bash
cd backend && python -m pytest -q
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `TCP_DATA_DIR` | Where projects and drawings are stored | `backend/data` |
| `TCP_RULES_DIR` | Jurisdiction rule files | `rules/` |
| `TCP_ACCESS_KEY` | If set, users need `/?key=<value>` once (cookie) to use the app | unset (open) |
| `TCP_TILE_URL` / `TCP_TILE_ATTRIBUTION` | Map tiles. Use a hosted provider in production (OSM's public tiles don't allow heavy use) | OSM standard tiles |
| `TCP_OVERPASS_URL`, `TCP_NOMINATIM_URL` | Map data services | public OSM endpoints |
| `TCP_CHROMIUM` | Path to a Chromium binary for PDF rendering, if Playwright's isn't installed | auto |

## Deploy

`Dockerfile` builds a single container (API, frontend, rules, Chromium for PDFs). Mount a volume
at `/data`. This suits Azure Container Apps or App Service in a project-owned account
(see docs/PLAN.md §5.1).

## Layout

```
backend/tcp_auto/
  ingest/      PDF -> text spans, scale, excluded regions (title block, notes)
  extract/     Construct/Remove keyword extraction (keywords.yaml is editable)
  site/        OpenStreetMap road lookup and geocoding
  rules/       rule loader/resolver/evaluator (reads rules/*.yaml)
  timeline/    night detection, peak-hour and work-hour checks
  layout/      template selection and device placement
  compliance/  checks shared by the generator and the editor
  report/      narrative, SVG plan drawing, HTML/PDF report
  email/       .eml draft builder
  api/         FastAPI app (serves frontend/)
frontend/      editor (Leaflet, no build step; Leaflet vendored)
rules/         jurisdiction rules (YAML) + source register
samples/       synthetic sample drawing
```
