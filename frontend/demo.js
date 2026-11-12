/* FlagPole static online demo (GitHub Pages / shared preview).
   Loaded before app.js only in the demo build. It answers the editor's /api calls from pre-built
   data (demo/data.json) and re-runs the compliance checks in the browser when devices move.
   Nothing is saved: reloading the page resets the demo. */
"use strict";
(function () {
  const BASE = new URL(".", document.currentScript.src).href;
  let DATA = null;
  const loaded = fetch(BASE + "demo/data.json").then(r => r.json()).then(d => { DATA = d; return d; });
  const realFetch = window.fetch.bind(window);
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const NOT_IN_DEMO = "This needs the full FlagPole app (desktop or server). The online demo uses pre-made sample projects.";

  // ---------------------------------------------------------------- links (images, previews, downloads)
  window.FP_LINK = function (path) {
    const m = path.match(/^\/api\/projects\/([a-f0-9]+)\/(report\.html|report\.pdf|checklist\.html|checklist\.pdf|email\.eml|drawing\/page\/(\d+)\.png)/);
    if (!m) return path;
    const pid = m[1], what = m[2];
    if (window.FP_EMBED && /\.(pdf|eml)$/.test(what)) {
      // Embedded previews (e.g. a Claude artifact) block downloads.
      setTimeout(() => window.status && status("Downloads aren't available in this preview. Use the GitHub Pages demo or the full app to download PDFs."));
      return "#";
    }
    const files = (DATA && DATA.files[pid]) || {};
    if (what.startsWith("drawing")) return BASE + (files["page" + m[3]] || "");
    const key = what.replace(".", "_");
    if (!files[key]) { setTimeout(() => window.status && status("Not available for this project in the demo.", true)); return "#"; }
    if (/^(report|checklist)\.html$/.test(what) && DATA.projects[pid] && DATA.projects[pid].plan && DATA.projects[pid].plan.version > 1) {
      setTimeout(() => window.status && status("The report shows the plan as generated; your demo edits aren't included."));
    }
    return BASE + files[key];
  };

  // ---------------------------------------------------------------- responses
  function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }
  function fail(msg, status = 400) { return json({ detail: msg }, status); }
  function listProjects() {
    return Object.values(DATA.projects).map(p => ({
      id: p.id, project_name: p.details.project_name, address: p.details.address, city: p.details.city,
      job_number: p.details.job_number, updated_at: p.updated_at, has_plan: !!p.plan,
    })).sort((a, b) => (a.project_name > b.project_name ? 1 : -1));
  }
  function newId() { return Math.random().toString(16).slice(2, 14).padEnd(12, "0"); }
  function touch(p) { p.updated_at = new Date().toISOString(); return p; }

  async function route(method, url, body) {
    await loaded;
    const path = url.pathname.replace(/^.*?\/api\//, "/api/");
    const q = url.searchParams;
    let m;
    if (path === "/api/config") return json(DATA.config);
    if (path === "/api/projects" && method === "GET") return json(listProjects());
    if (path === "/api/projects" && method === "POST") {
      const p = clone(DATA.blank_project); p.id = newId(); Object.assign(p.details, body || {});
      DATA.projects[p.id] = touch(p); return json(p);
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)$/))) {
      const p = DATA.projects[m[1]]; if (!p) return fail("Project not found", 404);
      if (method === "GET") return json(p);
      if (method === "PUT") {
        for (const k of ["details", "road", "work_center", "work_extent_ft"]) if (body && k in body) p[k] = body[k];
        return json(touch(p));
      }
      if (method === "DELETE") { delete DATA.projects[m[1]]; return json({ ok: true }); }
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)\/duplicate$/))) {
      const p = clone(DATA.projects[m[1]]); p.id = newId(); p.details.project_name += " (copy)";
      DATA.files[p.id] = DATA.files[m[1]]; DATA.originals[p.id] = DATA.originals[m[1]]; DATA.checklists[p.id] = DATA.checklists[m[1]];
      DATA.projects[p.id] = touch(p); return json(p);
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)\/items$/))) {
      const p = DATA.projects[m[1]]; p.extraction.items = body; return json(touch(p));
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)\/generate$/))) {
      const p = DATA.projects[m[1]];
      const orig = DATA.originals[m[1]];
      if (!orig) return fail("The online demo can't generate new plans. Open one of the sample projects, or run the full FlagPole app.");
      p.plan = clone(orig);
      setTimeout(() => window.status && status("Demo: this is the pre-generated plan for this sample. Changes to details or road need the full app."));
      return json(touch(p));
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)\/plan\/devices$/))) {
      const p = DATA.projects[m[1]];
      const prev = Object.fromEntries(p.plan.devices.map(d => [d.id, d]));
      body.forEach(d => { const o = prev[d.id]; if (!o || Math.abs(o.lat - d.lat) > 1e-9 || Math.abs(o.lon - d.lon) > 1e-9) d.origin = "manual"; });
      p.plan.devices = body; p.plan.version += 1;
      recheck(p);
      return json(touch(p));
    }
    if ((m = path.match(/^\/api\/projects\/([a-f0-9]+)\/checklist$/))) return json(DATA.checklists[m[1]] || []);
    if (/^\/api\/projects\/[a-f0-9]+\/drawing$/.test(path)) return fail("Uploading drawings needs the full FlagPole app. The demo projects already include a sample drawing.");
    if (path === "/api/rules/preview") {
      const key = [q.get("road_owner") || "city", q.get("city") || "", q.get("county") || ""].join("|");
      return json(DATA.rules_preview[key] || DATA.rules_preview["city||"]);
    }
    if (path === "/api/rules/layers") return json(DATA.rules_layers);
    if (path === "/api/rules/layer") return DATA.rules_layer[q.get("id")] ? json(DATA.rules_layer[q.get("id")]) : fail("Unknown rules layer", 404);
    if (path === "/api/rules/keys") return json(DATA.rule_keys);
    if (path.startsWith("/api/rules/proposals")) {
      if (method === "GET" && path === "/api/rules/proposals") return json([]);
      return fail("Proposing and reviewing rules needs the full FlagPole app (changes are saved on its server).");
    }
    if (path === "/api/settings/ai" && method === "GET") return json({ ...DATA.ai_settings, configured: false, reason: "AI drafting isn't available in the online demo." });
    if (path.startsWith("/api/settings/ai")) return fail("AI settings need the full FlagPole app.");
    if (path === "/api/road/lookup" || path === "/api/geocode") return fail("Map lookups need the full FlagPole app. Pan the map by hand in the demo.");
    return fail(NOT_IN_DEMO);
  }

  window.fetch = async function (input, init = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!/\/api\//.test(url.pathname) || url.origin !== location.origin) return realFetch(input, init);
    let body = null;
    if (init.body && typeof init.body === "string") { try { body = JSON.parse(init.body); } catch (_) { body = init.body; } }
    return route((init.method || "GET").toUpperCase(), url, body);
  };

  // ---------------------------------------------------------------- compliance (port of compliance/checks.py)
  const TOL = 0.95;
  const R_FT = 6371008.8 * 3.280839895;
  function project(pts, p) {
    const f = pts[0];
    const xy = (q) => [((q.lon - f.lon) * Math.PI / 180) * R_FT * Math.cos(f.lat * Math.PI / 180), ((q.lat - f.lat) * Math.PI / 180) * R_FT];
    const P = pts.map(xy), [px, py] = xy(p);
    let best = [Infinity, 0], cum = 0;
    for (let i = 0; i < P.length - 1; i++) {
      const [x0, y0] = P[i], [x1, y1] = P[i + 1], dx = x1 - x0, dy = y1 - y0, L2 = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / L2));
      const d = Math.hypot(px - (x0 + dx * t), py - (y0 + dy * t));
      if (d < best[0]) best = [d, cum + t * Math.sqrt(L2)];
      cum += Math.sqrt(L2);
    }
    return best[1];
  }
  function check(plan, road) {
    plan.devices.forEach(d => { d.station_ft = Math.round(project(road.centerline, d) * 10) / 10; });
    const D = plan.dimensions, dir = D.work_end_station_ft >= D.work_start_station_ft ? 1 : -1;
    const up = (st) => (D.work_start_station_ft - st) * dir;
    const out = [], issue = (severity, message, device_ids = []) => out.push({ severity, message, device_ids, rule_ref: null });
    const workLen = Math.abs(D.work_end_station_ft - D.work_start_station_ft);
    if (workLen < 250 * TOL) issue("error", `Work area is ${workLen.toFixed(0)} ft; minimum is 250 ft for two large utility trucks.`);
    const taper = plan.devices.filter(d => d.group === "taper" && (d.type === "cone" || d.type === "drum")).sort((a, b) => up(a.station_ft) - up(b.station_ft));
    if (taper.length >= 2) {
      const len = up(taper[taper.length - 1].station_ft) - up(taper[0].station_ft);
      if (len < D.taper_ft * TOL) issue("error", `Taper is ${len.toFixed(0)} ft; needs at least ${D.taper_ft.toFixed(0)} ft at ${D.speed_mph} mph (${D.taper_type}).`, taper.map(t => t.id));
      const dwT = (road.driveways || []).map(d => d.station_ft);
      let worst = 0; for (let i = 1; i < taper.length; i++) {
        const a = taper[i - 1].station_ft, b = taper[i].station_ft;
        if (dwT.some(s => s > Math.min(a, b) && s < Math.max(a, b))) continue; // gap left for a driveway
        worst = Math.max(worst, up(b) - up(a));
      }
      if (worst > D.taper_spacing_ft / TOL) issue("warning", `Taper device gap of ${worst.toFixed(0)} ft exceeds ${D.taper_spacing_ft.toFixed(0)} ft spacing.`, taper.map(t => t.id));
      const buf = up(taper[0].station_ft);
      if (buf < D.buffer_ft * TOL) issue("warning", `Buffer space is ${buf.toFixed(0)} ft; recommended ${D.buffer_ft.toFixed(0)} ft at ${D.speed_mph} mph.`, [taper[0].id]);
    } else if (plan.template !== "shoulder" || taper.length) issue("error", "No taper devices found.");
    const tangent = plan.devices.filter(d => d.group === "tangent").sort((a, b) => up(b.station_ft) - up(a.station_ft));
    const dws = (road.driveways || []).map(d => d.station_ft);
    let tg = 0; for (let i = 1; i < tangent.length; i++) {
      const a = tangent[i - 1].station_ft, b = tangent[i].station_ft;
      if (dws.some(s => s > Math.min(a, b) && s < Math.max(a, b))) continue; // gap left for a driveway
      tg = Math.max(tg, Math.abs(up(a) - up(b)));
    }
    if (tg > D.tangent_spacing_ft / TOL) issue("warning", `Tangent device gap of ${tg.toFixed(0)} ft exceeds ${D.tangent_spacing_ft.toFixed(0)} ft spacing.`);
    if (taper.length) {
      const signs = plan.devices.filter(d => d.group === "advance_warning" && d.type === "sign" && d.code !== "W16-1P").sort((a, b) => up(a.station_ft) - up(b.station_ft));
      const need = ["A", "B", "C"].map(k => D.sign_spacing_ft[k] || 0);
      let prev = up(taper[taper.length - 1].station_ft);
      signs.slice(0, 3).forEach((s, i) => {
        const gap = up(s.station_ft) - prev;
        if (gap < need[i] * TOL) issue("error", `${s.code} is ${gap.toFixed(0)} ft from ${i === 0 ? "taper" : "the " + signs[i - 1].code + " sign"}; needs at least ${need[i].toFixed(0)} ft (distance ${"ABC"[i]}).`, [s.id]);
        prev = up(s.station_ft);
      });
    }
    const has = (t) => plan.devices.some(d => d.type === t);
    if (plan.requirements.some(r => r.kind === "police" && r.required) && !has("police")) issue("error", "A police officer is required but none is placed on the plan.");
    if (plan.template === "two_lane_flagger" && !road.one_way) {
      const n = plan.devices.filter(d => d.type === "flagger").length;
      if (n < 2) issue("error", `One-lane two-way operation needs a flagger at each end (${n} placed).`);
    }
    if (plan.requirements.some(r => r.kind === "device" && /arrow/i.test(r.text)) && !has("arrow_board")) issue("error", "An arrow board is required by local rules but none is placed.");
    if (plan.night) {
      if (plan.devices.some(d => d.type === "cone" && d.group === "taper")) issue("warning", "Cones in tapers at night are strongly discouraged (ADOT); use drums or vertical panels.");
      const unlit = plan.devices.filter(d => d.type === "sign" && (d.group || "").startsWith("advance") && !d.lights).map(d => d.id);
      if (unlit.length) issue("warning", "Night work: advance warning signs should have flashing warning lights.", unlit);
    }
    return out;
  }
  function recheck(p) {
    const keep = p.plan.issues.filter(i => i.severity === "info" || i.message.includes("Phase") || (i.message.toLowerCase().includes("speed") && i.message.includes("confirmed")) || i.message.includes("Intersection") || i.message.includes("one-way") || i.message.includes("turn lane") || i.message.includes("Driveway"));
    p.plan.issues = keep.concat(check(p.plan, p.road));
  }

  // ---------------------------------------------------------------- in-page viewer (when pop-ups are blocked)
  const realOpen = window.open ? window.open.bind(window) : null;
  window.open = function (url, target, features) {
    const isDemoDoc = typeof url === "string" && /demo\/[a-f0-9]+\/(report|checklist)\.html$/.test(url);
    let w = null;
    if (!(isDemoDoc && window.FP_EMBED) && realOpen) { try { w = realOpen(url, target, features); } catch (_) { w = null; } }
    if (w || !isDemoDoc) return w;
    showDoc(url);
    return null;
  };
  async function showDoc(url) {
    const html = await realFetch(url).then(r => r.text());
    let ov = document.getElementById("demoDoc");
    if (!ov) {
      ov = document.createElement("div");
      ov.id = "demoDoc";
      ov.className = "demo-doc";
      ov.innerHTML = '<div class="demo-doc-bar"><b></b><button type="button">Close</button></div><iframe title="Document preview"></iframe>';
      ov.querySelector("button").onclick = () => ov.remove();
      document.body.appendChild(ov);
    }
    ov.querySelector("b").textContent = /checklist/.test(url) ? "Crew checklist" : "Agency report";
    ov.querySelector("iframe").srcdoc = html;
  }

  // ---------------------------------------------------------------- banner
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.className = "demo-banner";
    b.innerHTML = '<span><b>Online demo</b> · sample data, nothing is saved<span class="long">. Drag devices, open the report and checklist, browse the rules.</span></span><button type="button" aria-label="Hide demo notice">×</button>';
    b.querySelector("button").onclick = () => b.remove();
    document.body.prepend(b);
  });
})();
