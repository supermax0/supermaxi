"""Catalog: merges static scan + optional runtime scan + knowledge registry + tutorial registry.

Pure functions over plain data. Nothing here writes to the registry; it only reports.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from modules.ai_tutor import registry as tutorials
from modules.ai_tutor.analyzer.static_scan import ID_RE, KINDS, category_of, rule_matches
from modules.ai_tutor.chat import knowledge as knowledge_mod
from modules.ai_tutor.facts import FACT_NAMES

STATUSES = ("verified", "discovered", "knowledge_missing", "tutorial_missing", "broken", "stale", "disabled")
RUNTIME_SCHEMA = 1
MAX_RUNTIME_ELEMENTS = 6000
GLOBAL_PAGE = "global"


# -------------------------------------------------------------------- runtime

def validate_runtime(payload) -> dict:
    """Strictly validate an uploaded runtime scan (shape, id syntax, size). Returns a cleaned copy."""
    if not isinstance(payload, dict) or payload.get("schema") != RUNTIME_SCHEMA or not isinstance(payload.get("pages"), list):
        raise ValueError("runtime scan: unsupported shape")
    pages, total = [], 0
    for page in payload["pages"]:
        if not isinstance(page, dict) or not isinstance(page.get("id"), str) or not ID_RE.match(page["id"]):
            raise ValueError("runtime scan: bad page id")
        elements = []
        for el in page.get("elements") or []:
            total += 1
            if total > MAX_RUNTIME_ELEMENTS:
                raise ValueError("runtime scan: too many elements")
            if not isinstance(el, dict) or el.get("kind") not in KINDS or not isinstance(el.get("id"), str) or not ID_RE.match(el["id"]):
                raise ValueError("runtime scan: bad element")
            elements.append({"kind": el["kind"], "id": el["id"], "visible": bool(el.get("visible")),
                             "in_modal": bool(el.get("in_modal")), "label": str(el.get("label") or "")[:60] or None})
        route = str(page.get("route") or "")[:160]
        pages.append({"id": page["id"], "route": route, "accessible": bool(page.get("accessible", True)),
                      "status": int(page.get("status") or 0), "elements": elements})
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    return {
        "schema": RUNTIME_SCHEMA, "generated_at": str(payload.get("generated_at") or "")[:40], "pages": pages,
        "safety": {"clicked": [str(x)[:80] for x in safety.get("clicked", [])][:50],
                   "skipped": [{"id": str(s.get("id"))[:80], "class": str(s.get("class"))[:20]} for s in safety.get("skipped", []) if isinstance(s, dict)][:200],
                   "writes_observed": int(safety.get("writes_observed", 0))},
    }


# ----------------------------------------------------------- tutorial validation

def _refs_of_tutorial(definition: dict) -> list[tuple[str, str, str]]:
    """[(kind, id, step_id)] for every UI identifier a tutorial depends on."""
    refs = []
    for step in definition["steps"]:
        for ref in tutorials.target_refs(step):
            kind, ident = next(iter(ref.items()))
            refs.append((kind, ident, step["id"]))
        when = (step.get("reconcile") or {}).get("when") or {}
        if isinstance(when.get("visible"), dict):
            kind, ident = next(iter(when["visible"].items()))
            refs.append((kind, ident, step["id"]))
    return refs


def validate_tutorials(discovered: set, runtime_ids: set | None, static: dict) -> list[dict]:
    from modules.ai_tutor.validators import VALIDATORS

    pages = static["pages"]
    permissions = set(static["permissions"])
    endpoints = static["endpoints"]
    all_defs = tutorials.load_all()
    out = []
    for definition in all_defs.values():
        problems, targets = [], {}
        for kind, ident, step_id in _refs_of_tutorial(definition):
            if kind == "page":
                found = ident in pages
            else:
                found = (kind, ident) in discovered
            targets[(kind, ident)] = found
            if not found:
                problems.append({"severity": "error", "code": "target_missing", "step": step_id, "message": f"{kind} «{ident}» is not present in the system"})
            elif runtime_ids is not None and kind != "page" and (kind, ident) not in runtime_ids:
                problems.append({"severity": "warning", "code": "not_seen_at_runtime", "step": step_id, "message": f"{kind} «{ident}» exists in source but was not seen by the runtime scan"})
        for step in definition["steps"]:
            if step.get("page") and step["page"] not in pages:
                problems.append({"severity": "error", "code": "page_unknown", "step": step["id"], "message": f"page «{step['page']}» does not exist"})
            if step["type"] == "navigate":
                route = step["route"]
                valid = route.startswith("/clinics") and (route.rstrip("/").rsplit("/", 1)[-1] in pages or route.rstrip("/") == "/clinics")
                if not valid or not static["page_route_present"]:
                    problems.append({"severity": "error", "code": "route_unknown", "step": step["id"], "message": f"route «{route}» is not a clinics page"})
            if step["type"] == "wait_api_success":
                method, pattern = step["match"].get("method", "GET"), step["match"]["url"]
                if not any(method in e["methods"] and rule_matches(e["rule"], method, pattern) for e in endpoints):
                    problems.append({"severity": "error", "code": "api_unmatched", "step": step["id"], "message": f"no backend endpoint matches {method} {pattern}"})
            validator = step.get("validator") or (step.get("reconcile") or {}).get("validator")
            if validator and validator not in VALIDATORS:
                problems.append({"severity": "error", "code": "validator_unknown", "step": step["id"], "message": f"validator «{validator}» is not implemented"})
        if definition.get("completion_validator") and definition["completion_validator"] not in VALIDATORS:
            problems.append({"severity": "error", "code": "validator_unknown", "step": None, "message": "completion validator is not implemented"})
        for permission in definition.get("requires_permissions", []):
            if permission not in permissions:
                problems.append({"severity": "error", "code": "permission_unknown", "step": None, "message": f"permission «{permission}» is not defined"})
        first_page = next((s["page"] for s in definition["steps"] if s.get("page") in pages), None)
        if first_page and pages[first_page][1] not in definition.get("requires_permissions", []):
            problems.append({"severity": "warning", "code": "permission_not_declared", "step": None,
                             "message": f"page «{first_page}» needs «{pages[first_page][1]}» but the tutorial does not declare it"})
        dependencies = []
        for dep in definition.get("dependencies", []):
            target = all_defs.get(dep["tutorial"])
            ok = bool(target) and target["status"] != "disabled" and dep["fact"]["name"] in FACT_NAMES
            dependencies.append({"tutorial": dep["tutorial"], "exists": bool(target), "runnable": bool(target) and tutorials.is_runnable_status(target),
                                 "fact": dep["fact"], "message_ar": dep["message_ar"]})
            if not ok:
                problems.append({"severity": "error", "code": "dependency_missing", "step": None, "message": f"dependency tutorial «{dep['tutorial']}» is missing or disabled"})
        errors = [p for p in problems if p["severity"] == "error"]
        declared = definition["status"]
        status = declared if declared == "disabled" else ("broken" if errors else declared)
        out.append({
            "id": definition["id"], "version": definition["version"], "declared_status": declared, "status": status,
            "title_ar": definition["title_ar"], "steps": len(definition["steps"]), "problems": problems,
            "targets_total": len(targets), "targets_found": sum(1 for f in targets.values() if f),
            "dependencies": dependencies, "targets": sorted(f"{k}:{i}" for k, i in targets),
        })
    return out


# ------------------------------------------------------------------- catalog

def _selector(kind: str, ident: str) -> str:
    return f"[data-finora-{kind}='{ident}']"


def build_catalog(static: dict, runtime: dict | None = None, simulate_missing: set[str] | frozenset = frozenset(),
                  knowledge=None) -> dict:
    kb = knowledge or knowledge_mod.load()
    pages_cfg = static["pages"]

    # 1. discovered elements (static ∪ runtime), minus ids removed by a test-only simulation
    found: dict[tuple, dict] = {}
    for item in static["items"]:
        if item["id"] in simulate_missing:
            continue
        found[(item["kind"], item["id"])] = {
            "kind": item["kind"], "id": item["id"], "files": item["files"], "labels": list(item["labels"]), "category": item["category"],
            "page": item["page"], "dynamic": item["dynamic"], "static": True, "runtime": False, "visible": False, "in_modal": False,
            "runtime_pages": [],
        }
    runtime_ids: set | None = None
    if runtime:
        runtime_ids = set()
        for page in runtime["pages"]:
            for el in page["elements"]:
                if el["id"] in simulate_missing or el["kind"] == "page":
                    continue
                key = (el["kind"], el["id"])
                runtime_ids.add(key)
                entry = found.setdefault(key, {
                    "kind": el["kind"], "id": el["id"], "files": [], "labels": [], "category": category_of(el["kind"], el["id"]),
                    "page": None, "dynamic": False, "static": False, "runtime": False, "visible": False, "in_modal": False, "runtime_pages": [],
                })
                entry["runtime"] = True
                entry["visible"] = entry["visible"] or el["visible"]
                entry["in_modal"] = entry["in_modal"] or el["in_modal"]
                if page["id"] not in entry["runtime_pages"]:
                    entry["runtime_pages"].append(page["id"])
                if el["label"] and el["label"] not in entry["labels"]:
                    entry["labels"].append(el["label"])
    for entry in found.values():
        if entry["page"] is None and entry["runtime_pages"]:
            entry["page"] = GLOBAL_PAGE if len(entry["runtime_pages"]) > 2 else entry["runtime_pages"][0]

    # 2. references from the knowledge registry and from tutorials
    knowledge_refs = {(next(iter(r)), next(iter(r.values()))) for r in knowledge_mod.ui_references(include_discovered=False)}
    tutorial_refs: dict[tuple, set] = defaultdict(set)
    all_defs = tutorials.load_all()
    for definition in all_defs.values():
        for kind, ident, _ in _refs_of_tutorial(definition):
            tutorial_refs[(kind, ident)].add(definition["id"])
    discovered_keys = set(found)
    tutorial_report = validate_tutorials(discovered_keys, runtime_ids, static)
    tutorial_status = {t["id"]: t["status"] for t in tutorial_report}

    # 3. entries (union of discovered and referenced ids)
    keys = set(found) | {k for k in knowledge_refs if k[0] != "page"} | {k for k in tutorial_refs if k[0] != "page"}
    items = []
    for kind, ident in sorted(keys):
        base = found.get((kind, ident))
        category = base["category"] if base else category_of(kind, ident)
        page = base["page"] if base else None
        refs = sorted(tutorial_refs.get((kind, ident), []))
        permission = pages_cfg[page][1] if page in pages_cfg else None
        in_knowledge = (kind, ident) in knowledge_refs
        discovered = base is not None
        verified_by = [t for t in refs if tutorial_status.get(t) == "verified"]
        entry = {
            "kind": kind, "id": ident, "category": category, "page": page, "selector": _selector(kind, ident),
            "files": base["files"] if base else [], "label_ar": (base["labels"][0] if base and base["labels"] else None),
            "discovered": discovered, "discovered_static": bool(base and base["static"]), "discovered_runtime": bool(base and base["runtime"]),
            "runtime_visible": bool(base and base["visible"]), "runtime_in_modal": bool(base and base["in_modal"]),
            "knowledge_registered": in_knowledge, "tutorial_registered": bool(refs), "tutorials": refs,
            "verified": discovered and bool(verified_by), "permission": permission,
            "permission_mapped": (permission is not None) if category in ("feature", "submit", "structure") else None,
            "dynamic": bool(base and base["dynamic"]), "new": False,
        }
        entry["status"] = _status(entry, refs, tutorial_status)
        items.append(entry)

    pages = _pages(static, items, kb, runtime)
    dependencies = [{"from": t["id"], "to": d["tutorial"], "fact": d["fact"], "to_exists": d["exists"], "to_runnable": d["runnable"]}
                    for t in tutorial_report for d in t["dependencies"]]
    warnings = _warnings(static, runtime, items, tutorial_report)
    return {"items": items, "pages": pages, "tutorials": tutorial_report, "dependencies": dependencies,
            "coverage": coverage(items, pages, tutorial_report, runtime is not None), "warnings": warnings,
            "endpoints": _endpoint_summary(static["endpoints"])}


def _status(entry: dict, tutorial_ids: list[str], tutorial_status: dict) -> str:
    if not entry["discovered"]:
        # referenced by a tutorial => that tutorial is broken; referenced only by knowledge => the registry is stale
        return "broken" if entry["tutorial_registered"] else "stale"
    if entry["tutorials"] and all(tutorial_status.get(t) == "disabled" for t in entry["tutorials"]):
        return "disabled"
    if any(tutorial_status.get(t) == "broken" for t in tutorial_ids):
        return "broken"
    if entry["verified"]:
        return "verified"
    if entry["category"] in ("chrome", "submit", "structure"):
        return "discovered"  # plumbing: neither knowledge nor a lesson of its own is expected
    if not entry["knowledge_registered"] and not entry["tutorial_registered"]:
        return "knowledge_missing"
    if entry["tutorial_registered"]:
        return "discovered"  # used by a draft/unverified tutorial
    return "tutorial_missing" if entry["category"] == "feature" else "discovered"


def _pages(static: dict, items: list[dict], kb, runtime: dict | None) -> list[dict]:
    seen = {p["id"]: p for p in (runtime or {}).get("pages", [])}
    by_page: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if item["discovered"] and item["page"]:
            by_page[item["page"]].append(item)
    pages = []
    for page_id, (title, permission) in static["pages"].items():
        mine = by_page.get(page_id, [])
        runtime_page = seen.get(page_id)
        pages.append({
            "id": page_id, "title_ar": title, "route": "/clinics/" if page_id == "dashboard" else f"/clinics/{page_id}",
            "permission": permission, "knowledge_registered": f"page:{page_id}" in kb.entries,
            "instrumented": bool(mine), "actions": sum(1 for i in mine if i["kind"] == "action"),
            "fields": sum(1 for i in mine if i["kind"] == "field"), "sections": sum(1 for i in mine if i["kind"] == "section"),
            "runtime_seen": runtime_page is not None, "runtime_accessible": runtime_page["accessible"] if runtime_page else None,
        })
    return pages


def _endpoint_summary(endpoints: list[dict]) -> dict:
    by_permission = Counter(e["permission"] or "(none)" for e in endpoints)
    return {"count": len(endpoints), "by_permission": dict(sorted(by_permission.items()))}


def _warnings(static: dict, runtime: dict | None, items: list[dict], tutorial_report: list[dict]) -> list[dict]:
    warnings = []
    if static["unresolved"]:
        warnings.append({"code": "unresolved_placeholders", "count": len(static["unresolved"]),
                         "message": "some data-finora values contain template placeholders that could not be expanded"})
    if runtime is None:
        warnings.append({"code": "no_runtime_scan", "message": "no runtime scan uploaded: results are static-only"})
    elif runtime["safety"]["writes_observed"]:
        warnings.append({"code": "runtime_wrote_data", "count": runtime["safety"]["writes_observed"],
                         "message": "the runtime scan observed write requests; the scan is not trustworthy"})
    stale = [i["id"] for i in items if i["status"] == "stale"]
    if stale:
        warnings.append({"code": "stale_knowledge", "count": len(stale), "message": "knowledge registry references elements that no longer exist: " + ", ".join(stale[:8])})
    missing = [i["id"] for i in items if i["status"] == "tutorial_missing"]
    if missing:
        warnings.append({"code": "tutorial_missing", "count": len(missing), "message": "feature actions without a tutorial (not a failure): " + ", ".join(missing[:8])})
    unverified = [t["id"] for t in tutorial_report if t["status"] not in ("verified", "broken", "disabled")]
    if unverified:
        warnings.append({"code": "tutorial_unverified", "count": len(unverified), "message": "tutorials not marked verified: " + ", ".join(unverified)})
    return warnings


# ------------------------------------------------------------------ coverage

def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def coverage(items: list[dict], pages: list[dict], tutorial_report: list[dict], runtime_available: bool) -> dict:
    """Four separate measures (never merged into one number)."""
    actions = [i for i in items if i["kind"] == "action" and i["discovered"]]
    groups = {"all": actions}
    for category in ("feature", "navigation", "chrome", "submit"):
        groups[category] = [i for i in actions if i["category"] == category]

    def block(rows: list[dict]) -> dict:
        n = len(rows)
        knowledge = sum(1 for r in rows if r["knowledge_registered"])
        tutorial = sum(1 for r in rows if r["tutorial_registered"])
        verified = sum(1 for r in rows if r["verified"])
        return {"discovered": n, "knowledge": knowledge, "knowledge_pct": _pct(knowledge, n), "tutorial": tutorial, "tutorial_pct": _pct(tutorial, n),
                "verified": verified, "verified_pct": _pct(verified, n)}

    instrumented = sum(1 for p in pages if p["instrumented"])
    confirmed = sum(1 for a in actions if a["discovered_runtime"])
    return {
        "actions": {name: block(rows) for name, rows in groups.items()},
        "discovery": {"pages_instrumented": instrumented, "pages_total": len(pages), "pages_instrumented_pct": _pct(instrumented, len(pages)),
                      "runtime_available": runtime_available, "actions_confirmed_runtime": confirmed, "actions_discovered": len(actions),
                      "runtime_confirmed_pct": _pct(confirmed, len(actions)) if runtime_available else None},
        "tutorials": {"total": len(tutorial_report), "verified": sum(1 for t in tutorial_report if t["status"] == "verified"),
                      "broken": sum(1 for t in tutorial_report if t["status"] == "broken"),
                      "unverified": sum(1 for t in tutorial_report if t["status"] in ("draft", "needs_review"))},
        "counts": {"pages": len(pages), "sections": sum(1 for i in items if i["kind"] == "section" and i["discovered"]),
                   "actions": len(actions), "fields": sum(1 for i in items if i["kind"] == "field" and i["discovered"]),
                   "stale": sum(1 for i in items if i["status"] == "stale"), "broken": sum(1 for i in items if i["status"] == "broken")},
    }
