"""Snapshots (system_map.json), diff between scans, and read-only views used by the chat/registry."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from modules.ai_tutor.analyzer import static_scan
from modules.ai_tutor.analyzer.catalog import build_catalog, validate_runtime

SCHEMA = 1
HISTORY_KEEP = 10


def storage_dir() -> Path:
    override = os.environ.get("AI_TUTOR_SYSTEM_MAP_DIR")
    path = Path(override) if override else static_scan.ROOT / "instance" / "ai_tutor" / "system_map"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(name: str):
    path = storage_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # unreadable snapshot = no snapshot (the next scan rewrites it)


def _write(name: str, data) -> None:
    path = storage_dir() / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomic: readers never see a half-written file


def app_version() -> str:
    version = os.environ.get("APP_VERSION", "").strip()
    if version:
        return version
    version_file = static_scan.ROOT / "VERSION"
    return version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "dev"


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=static_scan.ROOT, capture_output=True, text=True, timeout=3, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None  # no git / not a checkout: the commit is optional metadata


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ building

def build_snapshot(runtime: dict | None = None, simulate_missing=frozenset()) -> dict:
    static = static_scan.scan_sources()
    catalog = build_catalog(static, runtime, set(simulate_missing))
    counts = catalog["coverage"]["counts"]
    return {
        "schema": SCHEMA,
        "meta": {
            "app_version": app_version(), "git_commit": git_commit(), "created_at": now_iso(),
            "pages_count": counts["pages"], "sections_count": counts["sections"], "actions_count": counts["actions"],
            "fields_count": counts["fields"], "runtime": runtime is not None,
            "runtime_generated_at": (runtime or {}).get("generated_at"),
            "simulated": sorted(simulate_missing), "fingerprint": static_scan.fingerprint(),
            "files_scanned": static["files_scanned"],
        },
        **catalog,
    }


def _key(item: dict) -> tuple:
    return item["kind"], item["id"]


def diff(previous: dict | None, current: dict) -> dict:
    """What changed between two scans. `previous=None` = first scan (nothing is reported as new)."""
    if previous is None:
        return {"first_scan": True, "added": [], "removed": [], "changed": [], "pages_changed": [], "broken_tutorials": [], "fixed_tutorials": [], "status_changes": []}
    old = {_key(i): i for i in previous["items"] if i["discovered"]}
    new = {_key(i): i for i in current["items"] if i["discovered"]}
    added = [{"kind": k[0], "id": k[1], "page": new[k]["page"]} for k in sorted(new.keys() - old.keys())]
    removed = [{"kind": k[0], "id": k[1], "page": old[k]["page"]} for k in sorted(old.keys() - new.keys())]
    changed = []
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        what = {f: [a[f], b[f]] for f in ("page", "files") if a[f] != b[f]}
        if what:
            changed.append({"kind": key[0], "id": key[1], "change": what})
    status_changes = [{"kind": k[0], "id": k[1], "from": old[k]["status"], "to": new[k]["status"]}
                      for k in sorted(old.keys() & new.keys()) if old[k]["status"] != new[k]["status"]]
    page_sets_old = {p: {i["id"] for i in old.values() if i["page"] == p} for p in {i["page"] for i in old.values() if i["page"]}}
    page_sets_new = {p: {i["id"] for i in new.values() if i["page"] == p} for p in {i["page"] for i in new.values() if i["page"]}}
    pages_changed = []
    for page in sorted(set(page_sets_old) | set(page_sets_new)):
        a, b = page_sets_old.get(page, set()), page_sets_new.get(page, set())
        if a != b:
            pages_changed.append({"page": page, "added": sorted(b - a), "removed": sorted(a - b)})
    was = {t["id"]: t["status"] for t in previous["tutorials"]}
    now = {t["id"]: t["status"] for t in current["tutorials"]}
    return {"first_scan": False, "added": added, "removed": removed, "changed": changed, "pages_changed": pages_changed,
            "broken_tutorials": sorted(t for t, s in now.items() if s == "broken" and was.get(t) != "broken"),
            "fixed_tutorials": sorted(t for t, s in now.items() if s != "broken" and was.get(t) == "broken"),
            "status_changes": status_changes}


# ------------------------------------------------------------------- storage

def load_latest() -> dict | None:
    return _read("latest.json")


def load_runtime() -> dict | None:
    return _read("runtime.json")


def save_runtime(payload) -> dict:
    cleaned = validate_runtime(payload)
    _write("runtime.json", cleaned)
    return cleaned


def clear_all() -> None:
    for path in storage_dir().rglob("*.json"):
        path.unlink()


def run_scan(*, simulate_missing=frozenset(), persist: bool = True) -> dict:
    """Scan, diff against the previous saved snapshot and (unless it is a simulation) save it as the new latest."""
    runtime = load_runtime()
    snapshot = build_snapshot(runtime, simulate_missing)
    previous = load_latest()
    changes = diff(previous, snapshot)
    new_keys = {(a["kind"], a["id"]) for a in changes["added"]}
    for item in snapshot["items"]:
        item["new"] = _key(item) in new_keys
    snapshot["diff"] = changes
    if persist and not simulate_missing:
        if previous is not None:
            history = storage_dir() / "history"
            history.mkdir(exist_ok=True)
            stamp = previous["meta"]["created_at"].replace(":", "").replace("+", "_")
            (history / f"{stamp}.json").write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
            for old in sorted(history.glob("*.json"))[:-HISTORY_KEEP]:
                old.unlink()
        _write("latest.json", snapshot)
    return snapshot


def is_stale(snapshot: dict | None) -> bool:
    """The sources/registries changed after this snapshot was taken."""
    return snapshot is None or snapshot["meta"].get("fingerprint") != static_scan.fingerprint()


# ------------------------------------------ cached read-only views (hot paths)

_CACHE: dict = {"at": 0.0, "mtime": None, "snapshot": None, "fresh": False}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 30.0


def current_snapshot() -> dict | None:
    """The latest snapshot if it still matches the sources (30 s cache; never scans during a request)."""
    with _CACHE_LOCK:
        now = time.monotonic()
        path = storage_dir() / "latest.json"
        mtime = path.stat().st_mtime_ns if path.exists() else None
        if now - _CACHE["at"] < CACHE_TTL and _CACHE["mtime"] == mtime:
            return _CACHE["snapshot"] if _CACHE["fresh"] else None
        snapshot = load_latest()
        fresh = bool(snapshot) and not is_stale(snapshot)
        _CACHE.update(at=now, mtime=mtime, snapshot=snapshot, fresh=fresh)
        return snapshot if fresh else None


def reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.update(at=0.0, mtime=None, snapshot=None, fresh=False)


def broken_tutorial_ids() -> set[str]:
    snapshot = current_snapshot()
    return {t["id"] for t in snapshot["tutorials"] if t["status"] == "broken"} if snapshot else set()
