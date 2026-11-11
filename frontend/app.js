/* TCP-Auto editor (no build step). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const state = {
  config: null,
  project: null,
  mode: null, // 'work' | 'centerline' | 'intersection' | 'place:<type>'
  draftLine: [],
  selected: null,
};

// ---------------------------------------------------------------- API
async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}
function status(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg || "";
  el.style.color = isError ? "#fda29b" : "#fcd9bd";
  if (msg && !isError) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
}
async function guard(fn) {
  try { return await fn(); } catch (e) { status(e.message, true); console.error(e); }
}

// ---------------------------------------------------------------- local geometry (mirrors geo.py)
const R_FT = 6371008.8 * 3.280839895;
function frameFor(pts) { return { lat0: pts[0].lat, lon0: pts[0].lon }; }
function toXY(f, p) {
  return [((p.lon - f.lon0) * Math.PI / 180) * R_FT * Math.cos(f.lat0 * Math.PI / 180), ((p.lat - f.lat0) * Math.PI / 180) * R_FT];
}
function stationOf(pts, p) {
  const f = frameFor(pts); const xy = pts.map(q => toXY(f, q)); const [px, py] = toXY(f, p);
  let best = [Infinity, 0], cum = 0;
  for (let i = 0; i < xy.length - 1; i++) {
    const [x0, y0] = xy[i], [x1, y1] = xy[i + 1]; const dx = x1 - x0, dy = y1 - y0; const L2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / L2));
    const d = Math.hypot(px - (x0 + dx * t), py - (y0 + dy * t));
    if (d < best[0]) best = [d, cum + t * Math.sqrt(L2)];
    cum += Math.sqrt(L2);
  }
  return { station: best[1], distance: best[0] };
}

// ---------------------------------------------------------------- map
const map = L.map("map", { zoomControl: true }).setView([33.39, -111.80], 12);
const layers = {
  road: L.layerGroup().addTo(map),
  zones: L.layerGroup().addTo(map),
  devices: L.layerGroup().addTo(map),
  draft: L.layerGroup().addTo(map),
};
let markers = {};

map.on("click", (e) => guard(() => onMapClick(e.latlng)));
map.on("dblclick", () => { if (state.mode === "centerline") finishCenterline(); });

function setMode(mode, hint = "") {
  state.mode = mode;
  $$("button.active").forEach(b => b.classList.remove("active"));
  const ids = { work: "#modeWork", centerline: "#modeCenterline", intersection: "#modeIntersection" };
  if (ids[mode]) $(ids[mode]).classList.add("active");
  if (mode && mode.startsWith("place:")) { const b = $(`#palette button[data-type="${mode.slice(6)}"]`); if (b) b.classList.add("active"); }
  $("#modeHint").textContent = hint;
  map.getContainer().style.cursor = mode ? "crosshair" : "";
  if (mode === "centerline") { state.draftLine = []; layers.draft.clearLayers(); }
}

async function onMapClick(ll) {
  const p = state.project; if (!p) return;
  const pt = { lat: ll.lat, lon: ll.lng };
  if (state.mode === "work") {
    await save({ work_center: pt }); setMode(null); status("Work location set"); return;
  }
  if (state.mode === "centerline") {
    state.draftLine.push(pt);
    layers.draft.clearLayers();
    L.polyline(state.draftLine.map(q => [q.lat, q.lon]), { color: "#2e90fa", weight: 4, dashArray: "6 6" }).addTo(layers.draft);
    state.draftLine.forEach(q => L.circleMarker([q.lat, q.lon], { radius: 4, color: "#2e90fa" }).addTo(layers.draft));
    $("#modeHint").textContent = `${state.draftLine.length} point(s). Draw in one direction along the street, well past the work in both directions. Double-click or click "Draw road centerline" again to finish.`;
    return;
  }
  if (state.mode === "intersection") {
    if (!p.road) throw new Error("Save the road centerline first");
    const { station, distance } = stationOf(p.road.centerline, pt);
    if (distance > 200) throw new Error("Click closer to the road centerline");
    const name = prompt("Cross street name?", "") ?? "";
    const signalized = confirm("Is this intersection signalized? (OK = yes)");
    p.road.intersections.push({ station_ft: Math.round(station), cross_street: name, signalized });
    p.road.intersections.sort((a, b) => a.station_ft - b.station_ft);
    await save({ road: p.road }); setMode(null); return;
  }
  if (state.mode && state.mode.startsWith("place:")) {
    if (!p.plan) throw new Error("Generate a plan first");
    const type = state.mode.slice(6);
    const dv = { id: Math.random().toString(16).slice(2, 14), type, lat: pt.lat, lon: pt.lon, origin: "manual", direction: "forward", group: groupFor(type), label: type };
    if (type === "sign") {
      dv.code = (prompt("Sign code (e.g. W20-1, W20-5R, W4-2R, G20-2, R9-9)", "W20-1") || "W20-1").toUpperCase();
      dv.label = dv.code;
      dv.group = dv.code.startsWith("G20") ? "termination" : "advance_warning";
    }
    p.plan.devices.push(dv);
    setMode(null);
    await saveDevices();
  }
}
function groupFor(type) {
  return { cone: "tangent", drum: "tangent", flagger: "flagger", police: "police", light_tower: "lighting", arrow_board: "taper", barricade3: "work" }[type] || "manual";
}
async function finishCenterline() {
  if (state.draftLine.length < 2) { status("Click at least two points along the road", true); return; }
  const p = state.project;
  const road = p.road ? { ...p.road } : defaultRoad();
  road.centerline = state.draftLine;
  road.intersections = []; // stations change with a new line
  road.sources = { ...(road.sources || {}), centerline: "user" };
  layers.draft.clearLayers();
  setMode(null);
  await save({ road });
  status("Centerline saved");
}
function defaultRoad() {
  return { name: "", centerline: [], speed_mph: 35, speed_confirmed: false, lanes_forward: 1, lanes_backward: 1, lane_width_ft: 12, one_way: false, divided: false, road_class: "collector", has_bike_lane: false, has_sidewalk: true, intersections: [], sources: {} };
}

// ---------------------------------------------------------------- rendering
function drawRoad() {
  layers.road.clearLayers();
  const p = state.project; if (!p) return;
  if (p.road && p.road.centerline.length) {
    L.polyline(p.road.centerline.map(q => [q.lat, q.lon]), { color: "#344054", weight: 3, opacity: .7, dashArray: "2 6" }).addTo(layers.road).bindTooltip(p.road.name || "Centerline");
    const f = p.road.centerline;
    L.marker([f[0].lat, f[0].lon], { icon: L.divIcon({ className: "", html: '<div class="badge">start</div>' }) }).addTo(layers.road);
  }
  if (p.work_center) {
    L.circleMarker([p.work_center.lat, p.work_center.lon], { radius: 9, color: "#e8650f", weight: 3, fillOpacity: .2 }).addTo(layers.road).bindTooltip("Work location");
  }
}

function iconFor(dv) {
  const t = dv.type;
  let inner = "";
  if (t === "sign") {
    const reg = (dv.code || "").startsWith("R") ? " reg" : "";
    inner = `<div class="dv dv-sign${reg}"></div><div class="dv-sign-label">${esc(dv.code || "")}</div>`;
  } else if (t === "flagger") inner = '<div class="dv dv-flagger">F</div>';
  else if (t === "police") inner = '<div class="dv dv-police">P</div>';
  else if (t === "arrow_board") inner = '<div class="dv dv-arrow_board">&#x27A4;</div>';
  else if (t === "truck") inner = `<div class="dv dv-truck" style="transform:rotate(${(dv.rotation_deg || 0) - 90}deg)">TRK</div>`;
  else inner = `<div class="dv dv-${t}"></div>`;
  const cls = ["dv-wrap", state.selected === dv.id ? "selected" : "", (state.flagged || []).includes(dv.id) ? "flagged" : ""].join(" ");
  return L.divIcon({ className: cls, html: `<div style="position:relative;display:flex;justify-content:center">${inner}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function drawPlan(fit = false) {
  layers.zones.clearLayers(); layers.devices.clearLayers(); markers = {};
  const plan = state.project && state.project.plan; if (!plan) return;
  const styles = { roadway: { color: "#475467", weight: 1, fillColor: "#98a2b3", fillOpacity: .35, interactive: false }, work_area: { color: "#c05800", fillColor: "#f07c1b", fillOpacity: .35, weight: 1 }, buffer: { color: "#999", fillOpacity: .1, weight: 1, dashArray: "4" }, taper: { color: "#f07c1b", fillOpacity: .15, weight: 1 }, reduced_speed: { color: "#1d4ed8", fillOpacity: .04, weight: 1, dashArray: "6" } };
  plan.zones.forEach(z => L.polygon(z.polygon.map(q => [q.lat, q.lon]), styles[z.kind] || {}).addTo(layers.zones).bindTooltip(z.label));
  plan.devices.forEach(dv => {
    const m = L.marker([dv.lat, dv.lon], { icon: iconFor(dv), draggable: true, title: `${dv.label || dv.type}${dv.code ? " (" + dv.code + ")" : ""}` });
    m.on("click", (e) => { L.DomEvent.stopPropagation(e); select(dv.id); });
    m.on("dragend", () => guard(async () => { const ll = m.getLatLng(); dv.lat = ll.lat; dv.lon = ll.lng; await saveDevices(); }));
    m.bindTooltip(`${esc(dv.label || dv.type)}${dv.lights ? "<br>" + esc(dv.lights) : ""}${dv.origin === "manual" ? "<br><i>moved/added by user</i>" : ""}`);
    m.addTo(layers.devices); markers[dv.id] = m;
  });
  if (fit) {
    const b = L.latLngBounds(plan.devices.map(d => [d.lat, d.lon]));
    if (b.isValid()) map.fitBounds(b.pad(0.1));
  }
}
function select(id) {
  state.selected = state.selected === id ? null : id;
  $("#deleteDevice").disabled = !state.selected;
  drawPlan();
}

function renderIssues() {
  const plan = state.project && state.project.plan;
  const ul = $("#issues"); ul.innerHTML = "";
  const rq = $("#reqs"); rq.innerHTML = "";
  $("#dims").textContent = "";
  if (!plan) return;
  const order = { error: 0, warning: 1, info: 2 };
  [...plan.issues].sort((a, b) => order[a.severity] - order[b.severity]).forEach(i => {
    const li = document.createElement("li");
    li.className = i.severity + (i.device_ids && i.device_ids.length ? " clickable" : "");
    li.innerHTML = `${esc(i.message)}${i.rule_ref ? `<span class="cite">${esc(i.rule_ref)}</span>` : ""}`;
    if (i.device_ids && i.device_ids.length) li.onclick = () => { state.flagged = i.device_ids; drawPlan(); const m = markers[i.device_ids[0]]; if (m) map.panTo(m.getLatLng()); };
    ul.appendChild(li);
  });
  if (!plan.issues.length) ul.innerHTML = '<li class="info">No issues found.</li>';
  plan.requirements.forEach(r => {
    const li = document.createElement("li");
    li.className = r.kind === "police" && r.required ? "error" : "info";
    li.innerHTML = `${r.kind === "police" && r.required ? "<b>Police officer required:</b> " : ""}${esc(r.text)}${r.required ? "" : ' <span class="muted">(may be required)</span>'}${r.verified ? "" : ' <span class="tag">confirm with agency</span>'}${r.citation ? `<span class="cite">${esc(r.citation)}</span>` : ""}`;
    rq.appendChild(li);
  });
  const d = plan.dimensions;
  $("#dims").innerHTML = `Template: <b>${esc(d.template)}</b>${plan.night ? " (night)" : ""} · ${d.speed_mph} mph · work area ${Math.round(d.work_area_ft)} ft · buffer ${Math.round(d.buffer_ft)} ft · taper ${Math.round(d.taper_ft)} ft (${esc(d.taper_type)}) · signs A/B/C ${d.sign_spacing_ft.A}/${d.sign_spacing_ft.B}/${d.sign_spacing_ft.C} ft · spacing ${d.taper_spacing_ft}/${d.tangent_spacing_ft} ft`;
}

// ---------------------------------------------------------------- drawing step
function renderDrawing() {
  const p = state.project;
  const ex = p.extraction;
  $("#drawingInfo").textContent = p.drawing_filename ? `${p.drawing_filename} – ${ex ? ex.items.length : 0} items found${p.work_extent_ft ? `, spread ≈ ${Math.round(p.work_extent_ft)} ft` : ""}` : "No drawing uploaded yet.";
  const wrap = $("#sheetWrap");
  const list = $("#itemList"); list.innerHTML = "";
  if (!ex || !ex.pages.length) { wrap.classList.add("hidden"); return; }
  const page = ex.pages.find(pg => ex.items.some(i => i.page === pg.page)) || ex.pages[0];
  wrap.classList.remove("hidden");
  const img = $("#sheetImg");
  const src = `/api/projects/${p.id}/drawing/page/${page.page}.png?v=${encodeURIComponent(p.updated_at)}`;
  if (img.dataset.src !== src) { img.src = src; img.dataset.src = src; }
  const dots = $("#sheetDots"); dots.innerHTML = "";
  ex.items.filter(i => i.page === page.page).forEach(i => {
    const d = document.createElement("div");
    d.className = `dot ${i.action} ${i.included ? "" : "off"}`;
    d.style.left = (100 * i.x / page.width) + "%"; d.style.top = (100 * i.y / page.height) + "%";
    d.title = i.label_text; dots.appendChild(d);
  });
  wrap.onclick = (e) => guard(async () => {
    const r = img.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * page.width, y = (e.clientY - r.top) / r.height * page.height;
    const action = confirm("Add a CONSTRUCT item here? (Cancel = REMOVE)") ? "construct" : "remove";
    const label = prompt("Label (e.g. 45' pole)", "") || "(added by user)";
    ex.items.push({ id: Math.random().toString(16).slice(2, 14), action, device_type: null, label_text: label, page: page.page, x, y, confidence: 1, source: "user", included: true });
    await putItems();
  });
  ex.items.forEach((i, k) => {
    const li = document.createElement("li");
    li.innerHTML = `<input type="checkbox" ${i.included ? "checked" : ""}><span class="badge ${i.action}">${i.action}</span><span class="grow">${esc(i.label_text)}</span><span class="badge">${esc(i.device_type || "")}</span>`;
    $("input", li).onchange = (e) => guard(async () => { i.included = e.target.checked; await putItems(); });
    list.appendChild(li);
  });
  (ex.warnings || []).forEach(w => { const li = document.createElement("li"); li.innerHTML = `<span class="tag">note</span> ${esc(w)}`; list.appendChild(li); });
}
async function putItems() {
  state.project = await api(`/api/projects/${state.project.id}/items`, { method: "PUT", json: state.project.extraction.items });
  renderDrawing();
}

// ---------------------------------------------------------------- details step
function fillDetails() {
  const d = state.project.details, f = $("#detailsForm");
  for (const el of f.elements) {
    if (!el.name) continue;
    const [obj, key] = el.name.startsWith("c.") ? [d.contacts, el.name.slice(2)] : [d, el.name];
    if (el.type === "checkbox") el.checked = !!obj[key]; else el.value = obj[key] ?? "";
  }
  const tb = $("#phaseRows"); tb.innerHTML = "";
  d.phases.forEach((ph, k) => addPhaseRow(ph));
  if (!d.phases.length) addPhaseRow(null);
  previewRules();
}
function addPhaseRow(ph) {
  const today = new Date().toISOString().slice(0, 10);
  ph = ph || { name: "Work", start_date: today, end_date: today, start_time: "08:30", end_time: "15:30", days: [0, 1, 2, 3, 4] };
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input class="pn" value="${esc(ph.name)}"></td><td><input class="ps" type="date" value="${ph.start_date}"></td><td><input class="pe" type="date" value="${ph.end_date}"></td>
    <td><input class="pst" type="time" value="${String(ph.start_time).slice(0, 5)}"></td><td><input class="pet" type="time" value="${String(ph.end_time).slice(0, 5)}"></td>
    <td><input class="pd" value="${(ph.days || []).map(i => DAYS[i]).join(",")}" title="e.g. Mon,Tue,Wed"></td><td><button type="button" class="danger">×</button></td>`;
  $("button", tr).onclick = () => tr.remove();
  $("#phaseRows").appendChild(tr);
}
function readDetails() {
  const d = structuredClone(state.project.details), f = $("#detailsForm");
  for (const el of f.elements) {
    if (!el.name) continue;
    const [obj, key] = el.name.startsWith("c.") ? [d.contacts, el.name.slice(2)] : [d, el.name];
    obj[key] = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
  }
  d.phases = $$("#phaseRows tr").map(tr => ({
    name: $(".pn", tr).value || "Work", start_date: $(".ps", tr).value, end_date: $(".pe", tr).value || $(".ps", tr).value,
    start_time: $(".pst", tr).value, end_time: $(".pet", tr).value,
    days: $(".pd", tr).value.split(",").map(s => DAYS.indexOf(s.trim().slice(0, 3))).filter(i => i >= 0),
  })).filter(ph => ph.start_date);
  return d;
}
async function previewRules() {
  const d = state.project.details;
  const q = new URLSearchParams({ city: d.city, county: d.county, road_owner: d.road_owner });
  const r = await api(`/api/rules/preview?${q}`);
  const peak = r.peak_hours ? `Peak-hour limits: ${r.peak_hours.weekdays.join(", ")} on ${r.peak_hours.road_class.join("/")} streets.` : "No peak-hour rule loaded.";
  const police = r.police_triggers.map(t => `${esc(t.role)}${t.verified ? "" : " (unverified)"}`).join("; ");
  $("#rulesPreview").innerHTML = `<b>Rules:</b> ${r.chain.map(esc).join(" → ")}<br>${esc(peak)}${police ? "<br>Police: " + police : ""}${r.warnings.map(w => "<br>⚠ " + esc(w)).join("")}`;
}

// ---------------------------------------------------------------- road step
function fillRoad() {
  const r = state.project.road || defaultRoad(), f = $("#roadForm");
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") el.checked = !!r[el.name]; else el.value = r[el.name] ?? "";
  }
  const ul = $("#intList"); ul.innerHTML = "";
  (r.intersections || []).forEach((ix, k) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="grow">${esc(ix.cross_street || "(unnamed)")} @ ${Math.round(ix.station_ft)} ft</span><label class="check"><input type="checkbox" ${ix.signalized ? "checked" : ""}> signal</label><button type="button" class="danger">×</button>`;
    $("input", li).onchange = (e) => { ix.signalized = e.target.checked; };
    $("button", li).onclick = () => { r.intersections.splice(k, 1); fillRoad(); };
    ul.appendChild(li);
  });
  const src = r.sources || {};
  $("#roadSources").textContent = Object.keys(src).length ? "Sources: " + Object.entries(src).map(([k, v]) => `${k}: ${v}`).join(", ") : "";
}
function readRoad() {
  const r = structuredClone(state.project.road || defaultRoad()), f = $("#roadForm");
  for (const el of f.elements) {
    if (!el.name) continue;
    r[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
  }
  if (state.project.road) r.intersections = state.project.road.intersections;
  r.sources = { ...(r.sources || {}), speed_mph: r.speed_confirmed ? "user" : (r.sources || {}).speed_mph || "rule_default" };
  return r;
}

// ---------------------------------------------------------------- save / load
async function save(partial) {
  state.project = await api(`/api/projects/${state.project.id}`, { method: "PUT", json: partial });
  renderAll(false);
}
async function saveDevices() {
  state.project = await api(`/api/projects/${state.project.id}/plan/devices`, { method: "PUT", json: state.project.plan.devices });
  drawPlan(); renderIssues();
}
function renderAll(fit) {
  renderDrawing(); fillDetails(); fillRoad(); drawRoad(); drawPlan(fit); renderIssues();
  $("#emailTo").value = $("#emailTo").value || "";
}
async function loadProject(id, fit = true) {
  state.project = await api(`/api/projects/${id}`);
  localStorage.setItem("tcp_project", id);
  renderAll(fit);
  if (fit && !state.project.plan) {
    const p = state.project;
    if (p.road && p.road.centerline.length) map.fitBounds(L.latLngBounds(p.road.centerline.map(q => [q.lat, q.lon])).pad(0.3));
    else if (p.work_center) map.setView([p.work_center.lat, p.work_center.lon], 17);
  }
}
async function refreshProjectList(selectId) {
  const list = await api("/api/projects");
  const sel = $("#projectSelect"); sel.innerHTML = "";
  list.forEach(p => {
    const o = document.createElement("option"); o.value = p.id;
    o.textContent = [p.project_name || "(untitled)", p.job_number, p.city].filter(Boolean).join(" · ");
    sel.appendChild(o);
  });
  if (selectId) sel.value = selectId;
  return list;
}

// ---------------------------------------------------------------- wire up
async function init() {
  state.config = await api("/api/config");
  $("#version").textContent = "v" + state.config.version;
  L.tileLayer(state.config.tile_url, { maxZoom: 20, maxNativeZoom: 19, attribution: state.config.tile_attribution }).addTo(map);
  $("#citySelect").innerHTML = '<option value="">(none / unincorporated)</option>' + state.config.cities.map(c => `<option>${esc(c)}</option>`).join("");
  $("#countySelect").innerHTML = '<option value="">(unknown)</option>' + state.config.counties.map(c => `<option>${esc(c)}</option>`).join("");

  let list = await refreshProjectList();
  if (!list.length) { const p = await api("/api/projects", { json: { project_name: "New project" } }); list = await refreshProjectList(p.id); }
  const last = localStorage.getItem("tcp_project");
  const id = list.some(p => p.id === last) ? last : list[0].id;
  $("#projectSelect").value = id;
  await loadProject(id);

  $("#projectSelect").onchange = (e) => guard(() => loadProject(e.target.value));
  $("#newProject").onclick = () => guard(async () => {
    const name = prompt("Project name", "") ?? ""; const p = await api("/api/projects", { json: { project_name: name } });
    await refreshProjectList(p.id); await loadProject(p.id);
  });
  $("#dupProject").onclick = () => guard(async () => { const p = await api(`/api/projects/${state.project.id}/duplicate`, { method: "POST" }); await refreshProjectList(p.id); await loadProject(p.id); status("Duplicated"); });

  $("#drawingFile").onchange = (e) => guard(async () => {
    const file = e.target.files[0]; if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    status("Reading drawing…");
    state.project = await api(`/api/projects/${state.project.id}/drawing`, { method: "POST", body: fd });
    renderAll(false); status(`Found ${state.project.extraction.items.length} work items`);
    e.target.value = "";
  });

  $("#detailsForm").onsubmit = (e) => { e.preventDefault(); guard(async () => { await save({ details: readDetails() }); await refreshProjectList(state.project.id); status("Details saved"); }); };
  $("#detailsForm").onchange = (e) => { if (["city", "county", "road_owner"].includes(e.target.name)) guard(async () => { state.project.details = readDetails(); await previewRules(); }); };
  $("#addPhase").onclick = () => addPhaseRow(null);

  $("#roadForm").onsubmit = (e) => { e.preventDefault(); guard(async () => { if (!state.project.road) throw new Error("Draw the centerline first"); await save({ road: readRoad() }); status("Road saved"); }); };
  $("#modeWork").onclick = () => setMode(state.mode === "work" ? null : "work", "Click the map where the work is (the center of the poles/equipment).");
  $("#modeCenterline").onclick = () => { if (state.mode === "centerline") finishCenterline(); else setMode("centerline", "Click points along the street in the direction you want as 'forward'. Extend about 1,500 ft past the work on both ends."); };
  $("#modeIntersection").onclick = () => setMode(state.mode === "intersection" ? null : "intersection", "Click where a cross street meets the centerline.");
  $("#lookupRoad").onclick = () => guard(async () => {
    const c = state.project.work_center; if (!c) throw new Error("Set the work location first");
    status("Looking up road…");
    const r = await api(`/api/road/lookup?lat=${c.lat}&lon=${c.lon}`);
    await save({ road: r.road });
    if (r.schools && r.schools.length && r.schools[0].distance_ft < 600 && !state.project.details.school_zone) {
      if (confirm(`${r.schools[0].name} is about ${r.schools[0].distance_ft} ft away. Mark this job as in a school zone?`)) {
        const d = state.project.details; d.school_zone = true; await save({ details: d });
      }
    }
    status(`Road found: ${r.road.name || "(unnamed)"}. Confirm the posted speed.`);
  });
  $("#geoBtn").onclick = () => guard(async () => {
    const res = await api(`/api/geocode?q=${encodeURIComponent($("#geoQuery").value)}`);
    if (!res.length) throw new Error("Address not found"); map.setView([res[0].lat, res[0].lon], 18); status(res[0].name);
  });

  $("#generate").onclick = () => guard(async () => {
    state.project = await api(`/api/projects/${state.project.id}/generate`, { method: "POST" });
    state.selected = null; state.flagged = [];
    drawPlan(true); renderIssues(); status("Draft plan generated");
    $("#issues").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $$("#palette button[data-type]").forEach(b => b.onclick = () => setMode(state.mode === "place:" + b.dataset.type ? null : "place:" + b.dataset.type, `Click the map to place a ${b.dataset.type}.`));
  $("#deleteDevice").onclick = () => guard(async () => {
    const plan = state.project.plan; plan.devices = plan.devices.filter(d => d.id !== state.selected);
    state.selected = null; $("#deleteDevice").disabled = true; await saveDevices();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { setMode(null); layers.draft.clearLayers(); }
    if ((e.key === "Delete" || e.key === "Backspace") && state.selected && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) $("#deleteDevice").click();
  });

  $("#previewReport").onclick = () => window.open(`/api/projects/${state.project.id}/report.html`, "_blank");
  $("#pdfReport").onclick = () => { window.location = `/api/projects/${state.project.id}/report.pdf`; };
  $("#emlReport").onclick = () => { const to = $("#emailTo").value.trim(); window.location = `/api/projects/${state.project.id}/email.eml${to ? "?to=" + encodeURIComponent(to) : ""}`; };
}

// Accordion: opening one step closes the others
$$("#panel > details").forEach(d => d.addEventListener("toggle", () => {
  if (d.open) $$("#panel > details").forEach(o => { if (o !== d) o.open = false; });
}));

init().catch(e => status(e.message, true));
