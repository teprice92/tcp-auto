"""Rule change proposals: draft -> review -> accept/reject.

Nothing reaches the planner until a reviewer accepts it. Accepted changes are written to the local
rules overlay (``<data>/rules_local/<layer>.yaml``), which the engine layers over the shipped rules.
A shared database can replace these files later without changing the review flow.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field

from ..models import new_id
from . import engine
from .schema import KEYS, check_value

_lock = threading.Lock()

Level = Literal["federal", "state", "county", "city"]


class RuleCite(BaseModel):
    source_title: str = ""
    section: str = ""


class RuleChange(BaseModel):
    id: str = Field(default_factory=new_id)
    op: Literal["set", "add_item", "remove"] = "set"
    key: str
    value: Any = None
    cite: RuleCite = Field(default_factory=RuleCite)
    quote: str = ""  # exact text from the source that supports the rule
    note: str = ""
    confidence: Optional[str] = None  # high | medium | low (AI drafts)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    current: Any = None  # current value in this layer, filled when read (for the diff)


class NewLayer(BaseModel):
    level: Level = "city"
    name: str
    state: str = "AZ"


class RuleProposal(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    author: str = ""
    layer_id: str
    new_layer: Optional[NewLayer] = None
    source_title: str = ""
    source_url: str = ""
    source_text: str = ""
    summary: str = ""
    questions: list[str] = Field(default_factory=list)
    changes: list[RuleChange] = Field(default_factory=list)
    origin: Literal["ai", "manual"] = "manual"
    model: Optional[str] = None
    status: Literal["pending", "accepted", "rejected"] = "pending"
    reviewer: str = ""
    reviewed_at: Optional[datetime] = None
    review_note: str = ""
    verified: bool = False


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def layer_id_for(new: NewLayer) -> str:
    s = engine.slug(new.name)
    return {"federal": f"federal/{s}", "state": f"states/{new.state.upper()}", "county": f"counties/{new.state.upper()}/{s}", "city": f"cities/{new.state.upper()}/{s}"}[new.level]


def list_layers() -> list[dict]:
    ids: set[str] = set()
    for root in (engine.RULES_DIR, engine.local_rules_dir()):
        if root.exists():
            for p in root.rglob("*.yaml"):
                rel = p.relative_to(root).with_suffix("").as_posix()
                if rel.count("/") >= 1 and not rel.startswith("sources"):
                    ids.add(rel)
    out = []
    for lid in sorted(ids):
        try:
            data = engine._load_file(lid, str(engine.RULES_DIR))
        except FileNotFoundError:
            continue
        j = data.get("jurisdiction", {}) or {}
        out.append({
            "id": lid, "name": j.get("name", lid), "level": j.get("level", ""), "status": data.get("status", ""),
            "rule_count": len(data.get("rules") or {}), "local_keys": data.get("_local_keys", []), "local_only": data.get("_local_only", False),
        })
    order = {"federal": 0, "state": 1, "state-agency": 2, "county": 3, "city": 4}
    return sorted(out, key=lambda l: (order.get(l["level"], 9), l["name"]))


def layer_rules(layer_id: str) -> dict:
    data = engine._load_file(layer_id, str(engine.RULES_DIR))
    return {"id": layer_id, "jurisdiction": data.get("jurisdiction", {}), "status": data.get("status", ""),
            "rules": data.get("rules") or {}, "local_keys": data.get("_local_keys", [])}


def _current(layer_id: str, key: str) -> Any:
    try:
        rule = (engine._load_file(layer_id, str(engine.RULES_DIR)).get("rules") or {}).get(key)
    except FileNotFoundError:
        return None
    return rule.get("value") if isinstance(rule, dict) else rule


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(p: RuleProposal) -> RuleProposal:
    for ch in p.changes:
        ch.errors, ch.warnings = [], []
        spec = KEYS.get(ch.key)
        if ch.op == "add_item" and spec and not spec.list_item:
            ch.op = "set"
            ch.warnings.append(f"{ch.key} isn't a list rule; changed to 'set'.")
        if ch.op == "set" and spec and spec.list_item:
            ch.op = "add_item"
            ch.warnings.append(f"{ch.key} is a list of triggers; this adds one trigger instead of replacing the list.")
        if ch.op != "remove":
            res = check_value(ch.key, ch.value)
            ch.value, ch.errors, ch.warnings = res.value, ch.errors + res.errors, ch.warnings + res.warnings
        if not (ch.cite.source_title or p.source_title):
            ch.errors.append("Every rule needs a source document title (for the citation).")
        if not ch.cite.section:
            ch.warnings.append("No section number given; reviewers can't easily check this rule.")
        ch.current = _current(p.layer_id, ch.key) if not p.new_layer else None
    if not p.changes:
        pass
    return p


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _dir() -> Path:
    d = engine.local_rules_dir().parent / "rule_proposals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(p: RuleProposal) -> RuleProposal:
    if not re.fullmatch(r"[a-f0-9]{6,32}", p.id):
        raise ValueError("bad id")
    with _lock:
        (_dir() / f"{p.id}.json").write_text(p.model_dump_json(indent=1), encoding="utf-8")
    return p


def get(pid: str) -> RuleProposal:
    path = _dir() / f"{pid}.json"
    if not re.fullmatch(r"[a-f0-9]{6,32}", pid) or not path.exists():
        raise KeyError(pid)
    p = RuleProposal.model_validate_json(path.read_text(encoding="utf-8"))
    if p.status == "pending":
        validate(p)
    return p


def list_all(status: str | None = None) -> list[RuleProposal]:
    out = []
    for f in _dir().glob("*.json"):
        try:
            p = RuleProposal.model_validate_json(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status is None or p.status == status:
            out.append(p)
    return sorted(out, key=lambda p: p.created_at, reverse=True)


def create(p: RuleProposal) -> RuleProposal:
    if p.new_layer:
        p.layer_id = layer_id_for(p.new_layer)
    elif not engine.layer_exists(p.layer_id):
        raise ValueError(f"Unknown rules layer '{p.layer_id}'")
    p.source_text = p.source_text[:60_000]
    return save(validate(p))


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def _source_id(title: str) -> str:
    return "local-" + engine.slug(title)[:48]


def _header(p: RuleProposal) -> dict:
    nl = p.new_layer
    if not nl:
        return {}
    extends = {"federal": [], "state": ["federal/mutcd-11"], "county": [f"states/{nl.state.upper()}"], "city": [f"states/{nl.state.upper()}"]}[nl.level]
    applies = {"federal": {}, "state": {"state": nl.state.upper()}, "county": {"road_owner": "county", "county": nl.name}, "city": {"road_owner": "city", "city": nl.name}}[nl.level]
    return {"id": p.layer_id, "level": nl.level, "name": nl.name if nl.level in ("county", "city") else nl.name, "extends": extends, "applies_to": applies}


def accept(pid: str, reviewer: str, verified: bool, note: str = "") -> RuleProposal:
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")
    p = get(pid)
    if p.status != "pending":
        raise ValueError(f"Proposal is already {p.status}.")
    errs = [e for ch in p.changes for e in ch.errors]
    if errs:
        raise ValueError("Fix these before accepting: " + "; ".join(errs[:5]))
    if not p.changes:
        raise ValueError("Proposal has no changes.")

    local = engine.local_rules_dir()
    path = local / f"{p.layer_id}.yaml"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        overlay = engine._read_yaml(path)
        if not overlay:
            overlay = {"jurisdiction": _header(p) or {"id": p.layer_id}, "status": "partial" if p.new_layer else "local-overlay", "rules": {}}
        rules = overlay.setdefault("rules", {})
        removed = overlay.setdefault("removed_rules", [])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta = {"accepted_by": reviewer.strip(), "accepted_at": now, "proposal": p.id}

        sources = engine._read_yaml(local / "sources.yaml")
        for ch in p.changes:
            title = ch.cite.source_title or p.source_title
            sid = _source_id(title)
            sources[sid] = {"title": title, "url": p.source_url, "added": now}
            cite = {"source": sid, "section": ch.cite.section}
            if ch.op == "remove":
                rules.pop(ch.key, None)
                if ch.key not in removed:
                    removed.append(ch.key)
                continue
            if ch.key in removed:
                removed.remove(ch.key)
            if ch.op == "add_item":
                existing = engine._load_file(p.layer_id, str(engine.RULES_DIR)).get("rules", {}).get(ch.key, {}) if engine.layer_exists(p.layer_id) else {}
                items = list((existing or {}).get("value") or [])
                # A reviewed trigger supersedes an unverified one with the same condition
                # (e.g. the placeholder school-zone rule once the city's actual text is found).
                items = [it for it in items if not (isinstance(it, dict) and it.get("when") == ch.value.get("when") and not it.get("verified"))]
                item = dict(ch.value)
                item.update({"cite": cite, "verified": verified, **({"note": ch.note} if ch.note else {}), **meta})
                if ch.quote:
                    item["quote"] = ch.quote
                rules[ch.key] = {"value": items + [item]}
            else:
                entry = {"value": ch.value, "cite": cite, "verified": verified, **meta}
                if ch.note:
                    entry["note"] = ch.note
                if ch.quote:
                    entry["quote"] = ch.quote
                rules[ch.key] = entry
            # keep the in-memory view current for later changes in the same proposal
            path.write_text(yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")
            engine.invalidate_cache()
        if not removed:
            overlay.pop("removed_rules", None)
        path.write_text(yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")
        (local / "sources.yaml").write_text(yaml.safe_dump(sources, sort_keys=True, allow_unicode=True), encoding="utf-8")
        with open(local / "changelog.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now, "proposal": p.id, "layer": p.layer_id, "reviewer": reviewer, "verified": verified,
                                "changes": [{"op": c.op, "key": c.key} for c in p.changes]}) + "\n")
        engine.invalidate_cache()

    p.status, p.reviewer, p.reviewed_at, p.review_note, p.verified = "accepted", reviewer.strip(), datetime.now(timezone.utc), note, verified
    return save(p)


def reject(pid: str, reviewer: str, note: str = "") -> RuleProposal:
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")
    p = get(pid)
    if p.status != "pending":
        raise ValueError(f"Proposal is already {p.status}.")
    p.status, p.reviewer, p.reviewed_at, p.review_note = "rejected", reviewer.strip(), datetime.now(timezone.utc), note
    return save(p)
