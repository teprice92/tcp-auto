/* FlagPole rules workspace: library, propose (AI or manual), review queue, AI settings.
   Uses helpers from app.js ($, $$, api, esc, status, guard). */
"use strict";

const rulesState = { layers: [], keys: [], drafts: [], ai: null, tab: "library", selectedLayer: null };
const me = () => { try { return localStorage.getItem("fp_name") || ""; } catch (_) { return ""; } };
const setMe = (v) => { try { localStorage.setItem("fp_name", v); } catch (_) {} };
const pretty = (v) => JSON.stringify(v, null, 2);
const levelLabel = { federal: "Federal", state: "State", "state-agency": "State agency", county: "County", city: "City / town" };

function openRules(tab) {
  $("#rulesView").classList.remove("hidden");
  rulesTab(tab || rulesState.tab);
}
function closeRules() { $("#rulesView").classList.add("hidden"); }

async function rulesTab(tab) {
  rulesState.tab = tab;
  $$("#rulesTabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $$(".rtab").forEach(el => el.classList.toggle("hidden", el.id !== "rtab-" + tab));
  await guard(async () => {
    if (tab === "library") await renderLibrary();
    if (tab === "propose") await renderPropose();
    if (tab === "review") await renderReview();
    if (tab === "settings") await renderSettings();
  });
}

async function refreshReviewCount() {
  const pending = await api("/api/rules/proposals?status=pending");
  const b = $("#reviewCount");
  b.textContent = pending.length; b.classList.toggle("hidden", !pending.length);
  const hb = $("#rulesBadge"); hb.textContent = pending.length; hb.classList.toggle("hidden", !pending.length);
  return pending;
}

// ---------------------------------------------------------------- library
async function renderLibrary() {
  rulesState.layers = await api("/api/rules/layers");
  const list = $("#layerList"); list.innerHTML = "";
  let lastLevel = "";
  rulesState.layers.forEach(l => {
    if (l.level !== lastLevel) { const h = document.createElement("div"); h.className = "lvl"; h.textContent = levelLabel[l.level] || l.level; list.appendChild(h); lastLevel = l.level; }
    const b = document.createElement("button");
    b.className = "layer" + (rulesState.selectedLayer === l.id ? " on" : "");
    b.innerHTML = `<span class="grow">${esc(l.name)}</span>${l.local_keys.length ? `<span class="chip info">${l.local_only ? "added here" : l.local_keys.length + " local"}</span>` : ""}<span class="chip ${l.status === "stub" ? "warn" : ""}">${esc(l.status)}</span>`;
    b.onclick = () => { rulesState.selectedLayer = l.id; renderLibrary(); };
    list.appendChild(b);
  });
  if (!rulesState.selectedLayer && rulesState.layers.length) rulesState.selectedLayer = rulesState.layers.find(l => l.level === "city")?.id || rulesState.layers[0].id;
  const detail = $("#layerDetail");
  if (!rulesState.selectedLayer) { detail.innerHTML = ""; return; }
  const L = await api(`/api/rules/layer?id=${encodeURIComponent(rulesState.selectedLayer)}`);
  const rows = Object.entries(L.rules).map(([k, r]) => {
    const isList = Array.isArray(r && r.value);
    const local = L.local_keys.includes(k);
    const items = isList ? r.value : [r];
    return `<div class="rule">
      <div class="rule-h"><b>${esc((rulesState.keys.find(x => x.key === k) || {}).label || k)}</b> <code>${esc(k)}</code>${local ? '<span class="chip info">accepted here</span>' : ""}</div>
      ${items.map(it => `<div class="rule-i"><pre>${esc(pretty(isList ? stripMeta(it) : it.value))}</pre>
        <div class="muted small">${esc(citeOf(it))} ${it.verified === false ? '<span class="tag">unverified</span>' : it.verified ? '<span class="chip ok">verified</span>' : ""}${it.accepted_by ? ` · accepted by ${esc(it.accepted_by)}` : ""}</div></div>`).join("")}
    </div>`;
  }).join("");
  detail.innerHTML = `<div class="detail-h"><div><h2>${esc(L.jurisdiction.name || L.id)}</h2><div class="muted">${esc(L.id)} · ${esc(L.status)}${L.jurisdiction.extends ? " · builds on " + esc(L.jurisdiction.extends.join(", ")) : ""}</div></div>
    <button class="primary" id="proposeForLayer">Propose a change</button></div>${rows || '<p class="muted">No rules yet.</p>'}`;
  $("#proposeForLayer").onclick = () => { rulesState.proposeLayer = L.id; rulesTab("propose"); };
}
function stripMeta(it) { const o = { ...it }; ["cite", "verified", "note", "quote", "accepted_by", "accepted_at", "proposal"].forEach(k => delete o[k]); return o; }
function citeOf(it) { const c = it.cite || {}; return [c.source, c.section].filter(Boolean).join(", "); }

// ---------------------------------------------------------------- propose
async function renderPropose() {
  if (!rulesState.keys.length) rulesState.keys = await api("/api/rules/keys");
  if (!rulesState.layers.length) rulesState.layers = await api("/api/rules/layers");
  rulesState.ai = await api("/api/settings/ai");
  const sel = $("#pLayer");
  sel.innerHTML = rulesState.layers.map(l => `<option value="${esc(l.id)}">${esc(levelLabel[l.level] || l.level)} – ${esc(l.name)}</option>`).join("") + '<option value="__new">+ Add a new city, county, or state…</option>';
  if (rulesState.proposeLayer) sel.value = rulesState.proposeLayer;
  $("#pNew").classList.toggle("hidden", sel.value !== "__new");
  sel.onchange = () => $("#pNew").classList.toggle("hidden", sel.value !== "__new");
  $("#pAuthor").value = $("#pAuthor").value || me();
  $("#aiState").innerHTML = rulesState.ai.configured
    ? `<span class="chip ok">AI ready</span> <span class="muted small">${esc(rulesState.ai.model)} · key ${esc(rulesState.ai.key_hint)} (${esc(rulesState.ai.source)})</span>`
    : `<span class="chip warn">No API key</span> <span class="muted small">Add one in <a href="#" id="toSettings">AI settings</a> to draft rules from text, or write them manually below.</span>`;
  const ts = $("#toSettings"); if (ts) ts.onclick = (e) => { e.preventDefault(); rulesTab("settings"); };
  $("#pDraft").disabled = !rulesState.ai.configured;
  $("#mKey").innerHTML = rulesState.keys.map(k => `<option value="${k.key}">${esc(k.label)} (${k.key})</option>`).join("");
  $("#mKey").onchange = () => fillExample();
  if (!$("#mValue").value) fillExample();
  renderManualList();
}
function fillExample() {
  const k = rulesState.keys.find(x => x.key === $("#mKey").value);
  $("#mValue").value = pretty(k.example);
  $("#mHelp").innerHTML = `${esc(k.help)}${k.list_item ? " Adds one trigger to the list." : ""}${k.used_by_planner ? "" : ' <span class="tag">reference only</span>'}` +
    (k.list_item ? `<br><span class="small">Conditions: ${Object.entries(k.conditions).map(([c, d]) => `<code>${esc(c)}</code> ${esc(d)}`).join(" · ")}</span>` : "");
}
function proposalBase() {
  const sel = $("#pLayer").value;
  const title = $("#pTitle").value.trim();
  if (!title) throw new Error("Enter the source document title (it becomes the citation).");
  const author = $("#pAuthor").value.trim(); setMe(author);
  const base = { layer_id: sel === "__new" ? "" : sel, source_title: title, source_url: $("#pUrl").value.trim(), author };
  if (sel === "__new") {
    const name = $("#pNewName").value.trim(); if (!name) throw new Error("Enter the name of the new jurisdiction.");
    base.new_layer = { level: $("#pNewLevel").value, name, state: "AZ" };
  }
  return base;
}
function renderManualList() {
  const ul = $("#mList"); ul.innerHTML = "";
  rulesState.drafts.forEach((c, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="grow"><b>${esc(c.key)}</b> <span class="muted small">§${esc(c.cite.section || "—")}</span><br><code class="small">${esc(JSON.stringify(c.value)).slice(0, 140)}</code></span><button type="button" class="danger">Remove</button>`;
    $("button", li).onclick = () => { rulesState.drafts.splice(i, 1); renderManualList(); };
    ul.appendChild(li);
  });
  $("#mSubmit").disabled = !rulesState.drafts.length;
}

// ---------------------------------------------------------------- review
async function renderReview() {
  if (!rulesState.layers.length) rulesState.layers = await api("/api/rules/layers");
  const pending = await refreshReviewCount();
  const wrap = $("#reviewList"); wrap.innerHTML = "";
  if (!pending.length) wrap.innerHTML = '<div class="emptybox"><b>Nothing waiting for review.</b><br><span class="muted">New rule proposals land here before the planner uses them.</span></div>';
  for (const summary of pending) {
    const p = await api(`/api/rules/proposals/${summary.id}`);
    wrap.appendChild(proposalCard(p));
  }
  const done = (await api("/api/rules/proposals")).filter(p => p.status !== "pending").slice(0, 20);
  $("#reviewHistory").innerHTML = done.length ? done.map(p => `<li><span class="chip ${p.status === "accepted" ? "ok" : "err"}">${p.status}</span> <b>${esc(p.layer_id)}</b> – ${esc(p.source_title)} <span class="muted small">by ${esc(p.reviewer)} ${p.reviewed_at ? new Date(p.reviewed_at).toLocaleDateString() : ""}${p.verified ? " · verified" : ""}${p.review_note ? " · " + esc(p.review_note) : ""}</span></li>`).join("") : '<li class="muted">No reviewed proposals yet.</li>';
}

function proposalCard(p) {
  const card = document.createElement("div");
  card.className = "pcard";
  const errs = p.changes.reduce((n, c) => n + c.errors.length, 0);
  card.innerHTML = `
    <div class="pcard-h">
      <div><h3>${esc(p.new_layer ? `New ${p.new_layer.level}: ${p.new_layer.name}` : ((rulesState.layers.find(l => l.id === p.layer_id) || {}).name || p.layer_id))}</h3>
      <div class="muted small">${esc(p.source_title)}${p.source_url ? ` · <a href="${esc(p.source_url)}" target="_blank" rel="noopener">source</a>` : ""} · ${p.origin === "ai" ? `drafted by AI (${esc(p.model || "")})` : "entered manually"}${p.author ? " · proposed by " + esc(p.author) : ""} · ${new Date(p.created_at).toLocaleString()}</div></div>
      <span class="chip ${errs ? "err" : "ok"}">${errs ? errs + " problem" + (errs > 1 ? "s" : "") : "Valid"}</span>
    </div>
    ${p.summary ? `<p>${esc(p.summary)}</p>` : ""}
    ${p.questions.length ? `<div class="qbox"><b>Questions for the reviewer</b><ul>${p.questions.map(q => `<li>${esc(q)}</li>`).join("")}</ul></div>` : ""}
    <div class="changes"></div>
    ${p.source_text ? `<details class="src"><summary>Show pasted source text</summary><pre>${esc(p.source_text)}</pre></details>` : ""}
    <div class="decide">
      <label>Reviewer <input class="rv" value="${esc(me())}" placeholder="Your name"></label>
      <label class="c"><input type="checkbox" class="vf"> I checked every change against the source document</label>
      <label class="wide">Note <input class="nt" placeholder="optional"></label>
      <div class="btns"><button class="save">Save edits</button><button class="danger rej">Reject</button><button class="primary acc" ${errs ? "disabled" : ""}>Accept into rules</button></div>
    </div>`;
  const box = $(".changes", card);
  p.changes.forEach((c) => {
    const el = document.createElement("div");
    el.className = "chg";
    const label = (rulesState.keys.find(k => k.key === c.key) || {}).label || c.key;
    const opText = { set: c.current == null ? "Add" : "Replace", add_item: "Add trigger to", remove: "Remove" }[c.op];
    el.innerHTML = `
      <div class="chg-h"><b>${esc(opText)} ${esc(label)}</b> <code>${esc(c.key)}</code> ${c.confidence ? `<span class="chip ${c.confidence === "high" ? "ok" : c.confidence === "low" ? "err" : "warn"}">${c.confidence} confidence</span>` : ""} <span class="muted small">§ ${esc(c.cite.section || "—")}</span></div>
      ${c.quote ? `<blockquote>${esc(c.quote)}</blockquote>` : ""}
      <div class="diff">
        <div><div class="dl">Current${c.op === "add_item" && Array.isArray(c.current) ? ` (${c.current.length} trigger${c.current.length === 1 ? "" : "s"})` : ""}</div>${currentView(c)}</div>
        <div><div class="dl">Proposed ${c.op === "add_item" ? "(new trigger)" : ""}</div><textarea class="val" spellcheck="false" rows="${Math.min(14, pretty(c.value).split("\n").length + 1)}">${esc(pretty(c.value))}</textarea></div>
      </div>
      <label class="sec">Section <input class="secin" value="${esc(c.cite.section || "")}"></label>
      ${c.errors.map(e => `<div class="msg err">✖ ${esc(e)}</div>`).join("")}${c.warnings.map(w => `<div class="msg warn">⚠ ${esc(w)}</div>`).join("")}`;
    el.dataset.id = c.id;
    box.appendChild(el);
  });
  const collect = () => p.changes.map(c => {
    const el = $(`.chg[data-id="${c.id}"]`, card);
    let value;
    try { value = JSON.parse($(".val", el).value); } catch (_) { throw new Error(`${c.key}: proposed value isn't valid JSON`); }
    return { ...c, value, cite: { ...c.cite, section: $(".secin", el).value } };
  });
  $(".save", card).onclick = () => guard(async () => { await api(`/api/rules/proposals/${p.id}`, { method: "PUT", json: collect() }); status("Edits saved and re-checked"); renderReview(); });
  $(".acc", card).onclick = () => guard(async () => {
    const reviewer = $(".rv", card).value.trim(); if (!reviewer) throw new Error("Enter your name as reviewer");
    setMe(reviewer);
    await api(`/api/rules/proposals/${p.id}`, { method: "PUT", json: collect() });
    await api(`/api/rules/proposals/${p.id}/accept`, { json: { reviewer, verified: $(".vf", card).checked, note: $(".nt", card).value } });
    status("Accepted. The planner uses these rules from now on."); renderReview(); onRulesChanged();
  });
  $(".rej", card).onclick = () => guard(async () => {
    const reviewer = $(".rv", card).value.trim(); if (!reviewer) throw new Error("Enter your name as reviewer");
    await api(`/api/rules/proposals/${p.id}/reject`, { json: { reviewer, note: $(".nt", card).value } });
    status("Proposal rejected"); renderReview();
  });
  return card;
}

function whenText(w) {
  return Object.entries(w || {}).map(([k, v]) => `${k.replace(/_/g, " ")}${v === true ? "" : ": " + (Array.isArray(v) ? v.join("/") : v)}`).join(", ");
}
function currentView(c) {
  if (c.current == null) return '<pre><span class="muted">(none)</span></pre>';
  if (c.op === "add_item" && Array.isArray(c.current)) {
    const same = (it) => JSON.stringify(it.when) === JSON.stringify((c.value || {}).when);
    return `<ul class="trig">${c.current.map(it => `<li class="${same(it) && !it.verified ? "replaced" : ""}"><b>${esc(it.role || (it.devices || []).join(", ") || it.personnel || "")}</b><span class="muted small"> when ${esc(whenText(it.when))}</span>${same(it) && !it.verified ? ' <span class="tag">will be replaced</span>' : it.verified === false ? ' <span class="tag">unverified</span>' : ""}</li>`).join("")}</ul>`;
  }
  return `<pre>${esc(pretty(c.current))}</pre>`;
}

// ---------------------------------------------------------------- settings
async function renderSettings() {
  const s = rulesState.ai = await api("/api/settings/ai");
  $("#aiStatus").innerHTML = s.configured ? `<span class="chip ok">Configured</span> key ${esc(s.key_hint)} from ${esc(s.source)}` : '<span class="chip warn">Not configured</span>';
  $("#aiModel").value = s.model;
  $("#aiClear").disabled = s.source !== "app settings";
}

function onRulesChanged() {
  rulesState.layers = [];
  if (typeof previewRules === "function" && state.project) previewRules();
  api("/api/config").then(cfg => {
    const cur = $("#citySelect").value;
    $("#citySelect").innerHTML = '<option value="">(none / unincorporated)</option>' + cfg.cities.map(c => `<option>${esc(c)}</option>`).join("");
    $("#citySelect").value = cur;
  });
}

// ---------------------------------------------------------------- wire up
(function initRules() {
  $("#openRules").onclick = () => openRules();
  $("#closeRules").onclick = closeRules;
  $$("#rulesTabs button").forEach(b => b.onclick = () => rulesTab(b.dataset.tab));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#rulesView").classList.contains("hidden") && !$("#dlg").open) closeRules(); });

  $("#pDraft").onclick = () => guard(async () => {
    const base = proposalBase();
    const text = $("#pText").value.trim(); if (!text) throw new Error("Paste the rule text first.");
    $("#pDraft").disabled = true; $("#pDraft").textContent = "Drafting…";
    try {
      await api("/api/rules/proposals/draft", { json: { ...base, text } });
      status("Draft ready for review"); $("#pText").value = "";
      rulesTab("review");
    } finally { $("#pDraft").disabled = false; $("#pDraft").textContent = "Draft with AI"; }
  });
  $("#mAdd").onclick = () => guard(async () => {
    let value;
    try { value = JSON.parse($("#mValue").value); } catch (_) {
      if ($("#mKey").value === "note") value = $("#mValue").value; else throw new Error("Value must be valid JSON (see the example).");
    }
    const key = $("#mKey").value;
    const k = rulesState.keys.find(x => x.key === key);
    rulesState.drafts.push({ op: k.list_item ? "add_item" : "set", key, value, cite: { source_title: "", section: $("#mSection").value.trim() }, quote: $("#mQuote").value.trim(), note: "" });
    $("#mQuote").value = ""; renderManualList();
  });
  $("#mSubmit").onclick = () => guard(async () => {
    const base = proposalBase();
    await api("/api/rules/proposals", { json: { ...base, source_text: $("#pText").value, changes: rulesState.drafts.map(c => ({ ...c, cite: { ...c.cite, source_title: base.source_title } })) } });
    rulesState.drafts = []; renderManualList(); status("Sent to review"); rulesTab("review");
  });
  $("#aiSave").onclick = () => guard(async () => {
    const key = $("#aiKey").value.trim();
    await api("/api/settings/ai", { method: "PUT", json: { api_key: key || null, model: $("#aiModel").value.trim() || null } });
    $("#aiKey").value = ""; status("AI settings saved"); renderSettings();
  });
  $("#aiClear").onclick = () => guard(async () => { await api("/api/settings/ai", { method: "PUT", json: { clear_key: true } }); status("Key removed"); renderSettings(); });
  api("/api/rules/keys").then(k => { rulesState.keys = k; }).catch(() => {});
  refreshReviewCount().catch(() => {});
})();
