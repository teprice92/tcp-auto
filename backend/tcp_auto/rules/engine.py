"""Jurisdiction rules: load YAML layers, resolve the chain for a project, evaluate triggers.

Layering (see rules/README.md):
- Each file may ``extends`` other files; parents load first and the more specific layer overrides.
- List rules (police triggers, required devices/personnel) are combined across layers.
- A few "practice" keys fall back to the ADOT guidelines when no layer in the chain defines them,
  because ADOT practice is the best available Arizona reference for things city manuals skip.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .. import RULES_DIR
from ..models import ProjectDetails, Requirement

LIST_KEYS = {"police_required", "required_devices", "required_personnel"}
REFERENCE_KEYS = {"night_work", "device_spacing", "speed_reduction", "pedestrian"}
REFERENCE_LAYER = "states/AZ-adot"

SOURCE_TITLES = {
    "tempe-tbm-2016": "City of Tempe Traffic Barricade Manual (Mar 2016)",
    "gilbert-te-app-2014": "Town of Gilbert Traffic Engineering Application packet (Aug 2014)",
    "qc-full-closure-2023": "Queen Creek TTC Full Roadway Closure Policy (Aug 2023)",
    "qc-dspm-notes-2007": "Queen Creek Design Standards: Construction Notes",
    "qc-tcp-app": "Queen Creek Traffic Control Plan application",
    "adot-ttcdg-2025": "ADOT Temporary Traffic Control Design Guidelines (Apr 2025)",
    "az-supp-mutcd11-2026": "Arizona Supplement to the MUTCD, 11th Ed. (Jan 2026)",
    "adot-school-2006": "ADOT Traffic Safety for School Areas Guidelines (2006)",
    "mesa-ttcm-2ed": "Mesa Temporary Traffic Control Manual, 2nd Ed.",
    "mesa-ttcm-1ed-2017": "Mesa Temporary Traffic Control Manual, 1st Ed. (2017)",
    "chandler-edsm": "Chandler Engineering & Design Standards Manual",
    "chandler-udm148": "Chandler Utility Permit Manual UDM-148",
    "phx-tbm-9r": "City of Phoenix Traffic Barricade Manual",
    "aj-code-row": "Apache Junction City Code (ROW permits)",
    "mutcd-11": "FHWA MUTCD, 11th Edition",
    "user-reported": "Reported by utility staff (not yet found in a published document)",
    "project": "FlagPole project default",
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def local_rules_dir() -> Path:
    """Rules accepted in the app (after review) live here, layered over the shipped rules/ files.

    v1 keeps them with the local install's data; a shared database replaces this later."""
    root = os.environ.get("TCP_DATA_DIR") or str(Path(__file__).resolve().parents[2] / "data")
    return Path(root) / "rules_local"


_generation = 0


def invalidate_cache() -> None:
    """Call after local rules change so the next resolve() re-reads files."""
    global _generation
    _generation += 1
    _load_cached.cache_clear()
    _local_sources.cache_clear()


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=128)
def _load_cached(layer_id: str, rules_dir: str, local_dir: str, gen: int) -> dict:
    base = _read_yaml(Path(rules_dir) / f"{layer_id}.yaml")
    over = _read_yaml(Path(local_dir) / f"{layer_id}.yaml")
    if not base and not over:
        raise FileNotFoundError(f"No rules layer '{layer_id}'")
    merged = copy.deepcopy(base) if base else {}
    if over:
        merged.setdefault("jurisdiction", over.get("jurisdiction", {}))
        if not base:
            merged["status"] = over.get("status", "partial")
        rules = dict(merged.get("rules") or {})
        for key in over.get("removed_rules", []) or []:
            rules.pop(key, None)
        rules.update(over.get("rules") or {})
        merged["rules"] = rules
        merged["_local_keys"] = sorted((over.get("rules") or {}).keys())
        merged["_local_only"] = not base
    return merged


def _load_file(layer_id: str, rules_dir: str) -> dict:
    return _load_cached(layer_id, str(rules_dir), str(local_rules_dir()), _generation)


def layer_exists(layer_id: str, rules_dir: Path = RULES_DIR) -> bool:
    return (Path(rules_dir) / f"{layer_id}.yaml").exists() or (local_rules_dir() / f"{layer_id}.yaml").exists()


@lru_cache(maxsize=4)
def _local_sources(local_dir: str, gen: int) -> dict:
    return _read_yaml(Path(local_dir) / "sources.yaml")


def source_title(src: str) -> str:
    local = _local_sources(str(local_rules_dir()), _generation)
    if src in local:
        return local[src].get("title", src) if isinstance(local[src], dict) else str(local[src])
    return SOURCE_TITLES.get(src, src)


def cite_text(cite: dict | None) -> str:
    if not cite:
        return ""
    src = cite.get("source", "")
    title = source_title(src)
    sec = cite.get("section")
    return f"{title}, {sec}" if sec else title


@dataclass
class RuleValue:
    key: str
    value: Any
    layer: str
    cite: str
    verified: bool
    note: str = ""


@dataclass
class ResolvedRules:
    chain: list[str]
    values: dict[str, RuleValue] = field(default_factory=dict)
    lists: dict[str, list[RuleValue]] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        rv = self.values.get(key)
        return rv.value if rv else default

    def rule(self, key: str) -> RuleValue | None:
        return self.values.get(key)


def _expand(layer_id: str, rules_dir: Path, seen: list[str]) -> None:
    if layer_id in seen:
        return
    data = _load_file(layer_id, str(rules_dir))
    for parent in (data.get("jurisdiction", {}) or {}).get("extends", []) or []:
        _expand(parent, rules_dir, seen)
    seen.append(layer_id)


def chain_for(details: ProjectDetails, rules_dir: Path = RULES_DIR) -> tuple[list[str], list[str]]:
    """Top-level layers that apply to a project, plus warnings about missing local rules."""
    warnings: list[str] = []
    layers = ["states/AZ"]
    if details.road_owner == "ADOT":
        layers.append("states/AZ-adot")
    elif details.road_owner == "tribal":
        warnings.append(
            "Work appears to be on tribal land. Tribal communities have their own permit processes; "
            "local rules were not applied."
        )
    elif details.road_owner == "county":
        cid = f"counties/AZ/{slug(details.county)}" if details.county else ""
        if cid and layer_exists(cid, rules_dir):
            layers.append(cid)
        else:
            warnings.append(f"No rules file for county '{details.county or 'unknown'}'. Local rules not loaded.")
    elif details.road_owner == "city":
        cid = f"cities/AZ/{slug(details.city)}" if details.city else ""
        if cid and layer_exists(cid, rules_dir):
            layers.append(cid)
        else:
            warnings.append(f"No rules file for city '{details.city or 'unknown'}'. Local rules not loaded.")
    else:
        warnings.append("Road owner unknown. Only federal and Arizona rules were applied.")
    return layers, warnings


def resolve(details: ProjectDetails, rules_dir: Path = RULES_DIR) -> ResolvedRules:
    top, warnings = chain_for(details, rules_dir)
    chain: list[str] = []
    for layer in top:
        _expand(layer, rules_dir, chain)
    res = ResolvedRules(chain=chain, warnings=warnings)

    for layer in chain:
        data = _load_file(layer, str(rules_dir))
        res.statuses[layer] = data.get("status", "unknown")
        for key, rule in (data.get("rules") or {}).items():
            if not isinstance(rule, dict):
                continue
            value = rule.get("value")
            if key in LIST_KEYS:
                items = value or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    res.lists.setdefault(key, []).append(
                        RuleValue(
                            key=key,
                            value=item,
                            layer=layer,
                            cite=cite_text(item.get("cite") or rule.get("cite")),
                            verified=bool(item.get("verified", rule.get("verified", False))),
                            note=item.get("note", ""),
                        )
                    )
            else:
                res.values[key] = RuleValue(
                    key=key,
                    value=value,
                    layer=layer,
                    cite=cite_text(rule.get("cite")),
                    verified=bool(rule.get("verified", False)),
                    note=rule.get("note", ""),
                )

    # ADOT practice as the Arizona reference for practice keys that no state/local layer defines
    # (it also takes precedence over the bare federal default)
    if REFERENCE_LAYER not in chain and layer_exists(REFERENCE_LAYER, rules_dir):
        ref = _load_file(REFERENCE_LAYER, str(rules_dir)).get("rules") or {}
        for key in REFERENCE_KEYS:
            current = res.values.get(key)
            if key in ref and (current is None or current.layer.startswith("federal/")):
                r = ref[key]
                res.values[key] = RuleValue(
                    key=key,
                    value=r.get("value"),
                    layer=f"{REFERENCE_LAYER} (reference practice)",
                    cite=cite_text(r.get("cite")),
                    verified=bool(r.get("verified", False)),
                )

    local = [l for l in chain if l.startswith(("cities/", "counties/"))]
    for l in local:
        if res.statuses.get(l) == "stub":
            warnings.append(
                f"Rules for {l.split('/')[-1]} are incomplete (built from web summaries). Confirm with the agency."
            )
    return res


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------


@dataclass
class Facts:
    """What we know about the job, used to evaluate rule conditions."""

    road_class: str
    speed_mph: int
    lane_closure: bool
    through_lanes_remaining: int
    school_zone: bool = False
    min_signal_distance_ft: float | None = None  # from the work zone to the nearest signal
    signal_in_zone: bool = False
    night: bool = False
    duration: str = "short_term"  # MUTCD duration category
    duration_days: int = 1
    flagging: bool = False
    bike_lane_closed: bool = False
    capacity_reduction_pct: float = 0.0
    during_peak: bool = False
    installing_devices: bool = True


ADVISORY_KEYS = {"city_review", "indicated_on_accepted_tcp", "per_section"}


def match(when: dict, f: Facts) -> bool | None:
    """True = condition met, False = not met, None = advisory (agency decides at review)."""
    if any(k in when for k in ADVISORY_KEYS):
        return None
    for key, want in when.items():
        if key == "school_zone":
            ok = f.school_zone == bool(want)
        elif key == "during":
            ok = want in ("school_hours", "work_hours") or (want == "peak_hours" and f.during_peak)
        elif key == "within_ft_of_signalized_intersection":
            ok = f.min_signal_distance_ft is not None and f.min_signal_distance_ft <= float(want)
        elif key == "signalized_intersection":
            ok = f.signal_in_zone == bool(want)
        elif key == "through_lanes_remaining":
            ok = f.through_lanes_remaining <= int(want)
        elif key == "road_class":
            ok = f.road_class in (want if isinstance(want, list) else [want])
        elif key == "lane_closure":
            ok = f.lane_closure == bool(want)
        elif key == "duration":
            ok = f.duration == want
        elif key == "duration_days_gt":
            ok = f.duration_days > int(want)
        elif key == "capacity_reduction_pct_gte":
            ok = f.capacity_reduction_pct >= float(want)
        elif key == "bike_lane_closed":
            ok = f.bike_lane_closed == bool(want)
        elif key == "installing_devices":
            ok = f.installing_devices == bool(want)
        elif key == "after_state_route_interchange":
            ok = not want  # not detected in v1; assume no interchange
        elif key == "operation":
            ok = False  # special operations (brake check, blasting) not generated in v1
        else:
            ok = False
        if not ok:
            return False
    return True


def evaluate(res: ResolvedRules, f: Facts) -> list[Requirement]:
    reqs: list[Requirement] = []
    for rv in res.lists.get("police_required", []):
        m = match(rv.value.get("when", {}), f)
        if m is False:
            continue
        reason = _describe(rv.value.get("when", {}))
        reqs.append(
            Requirement(
                kind="police",
                text=f"{rv.value.get('role', 'Police officer')}: {reason}",
                required=m is True,
                verified=rv.verified,
                citation=rv.cite,
            )
        )
    for key, kind in (("required_devices", "device"), ("required_personnel", "personnel")):
        for rv in res.lists.get(key, []):
            m = match(rv.value.get("when", {}), f)
            if not m:
                continue
            things = rv.value.get("devices") or [rv.value.get("personnel", "")]
            for t in things:
                reqs.append(Requirement(kind=kind, text=t, verified=rv.verified, citation=rv.cite))
    return reqs


def _describe(when: dict) -> str:
    parts = []
    for k, v in when.items():
        if k == "school_zone":
            parts.append("work in a school zone")
        elif k == "within_ft_of_signalized_intersection":
            parts.append(f"work within {v} ft of a signalized intersection")
        elif k == "city_review":
            parts.append("may be required by the agency at plan review")
        elif k == "indicated_on_accepted_tcp":
            parts.append("when the accepted plan calls for one")
        elif k == "per_section":
            parts.append(f"per section {v} (confirm requirement)")
        elif k == "signalized_intersection":
            parts.append("signalized intersection in the work zone")
        elif k == "through_lanes_remaining":
            parts.append(f"{v} through lane remaining")
        elif k == "during" and v == "school_hours":
            parts.append("during school hours")
    return "; ".join(parts) or "rule condition met"
