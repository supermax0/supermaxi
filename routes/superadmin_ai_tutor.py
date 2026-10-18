"""Super Admin / developer only: AI Tutor System Map (scan, snapshot, diff, runtime upload)."""
from __future__ import annotations

import os

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session

from modules.ai_tutor.analyzer import snapshot as snapshots

superadmin_ai_tutor_bp = Blueprint("superadmin_ai_tutor", __name__, url_prefix="/superadmin/ai-tutor")

MAX_RUNTIME_BYTES = 1_500_000


@superadmin_ai_tutor_bp.before_request
def _require_platform_admin():
    g.tenant = None  # always Core DB; tenants never reach this blueprint
    if session.get("is_superadmin") is True:
        return None
    if request.path.rstrip("/").endswith("/system-map") and request.method == "GET":
        return redirect("/superadmin/login")
    return jsonify({"error": "FORBIDDEN"}), 403


def simulation_enabled() -> bool:
    """Test-only: lets a scan pretend elements disappeared (never saved). Off unless explicitly enabled."""
    return os.environ.get("AI_TUTOR_ANALYZER_SIMULATION") == "1" or bool(current_app.config.get("TESTING"))


def _payload(snapshot: dict | None, *, simulated: bool = False) -> dict:
    runtime = snapshots.load_runtime()
    return {
        "ok": True, "snapshot": snapshot, "stale": snapshots.is_stale(snapshot) if snapshot else False, "simulated": simulated,
        "simulation_enabled": simulation_enabled(),
        "runtime": {"present": runtime is not None, "generated_at": (runtime or {}).get("generated_at"),
                    "pages": len((runtime or {}).get("pages", [])), "writes_observed": ((runtime or {}).get("safety") or {}).get("writes_observed")},
    }


@superadmin_ai_tutor_bp.get("/system-map")
def system_map_page():
    return render_template("superadmin_ai_tutor_system_map.html")


@superadmin_ai_tutor_bp.get("/system-map/data")
def system_map_data():
    return jsonify(_payload(snapshots.load_latest()))


@superadmin_ai_tutor_bp.post("/system-map/scan")
def system_map_scan():
    """Manual scan (static + registry validation, merged with the last uploaded runtime scan). Never during user requests."""
    body = request.get_json(silent=True) or {}
    simulate = body.get("simulate_missing") or []
    if simulate:
        if not simulation_enabled():
            return jsonify({"ok": False, "error": "simulation is disabled"}), 403
        if not isinstance(simulate, list) or not all(isinstance(x, str) and len(x) < 80 for x in simulate):
            return jsonify({"ok": False, "error": "simulate_missing must be a list of ids"}), 400
    snapshot = snapshots.run_scan(simulate_missing=frozenset(simulate), persist=not simulate)
    snapshots.reset_cache()
    return jsonify(_payload(snapshot, simulated=bool(simulate)))


@superadmin_ai_tutor_bp.post("/system-map/reset")
def system_map_reset():
    """Test-only: forget every saved snapshot so a browser spec starts (and ends) from a known state."""
    if not simulation_enabled():
        return jsonify({"ok": False, "error": "reset is disabled"}), 403
    snapshots.clear_all()
    snapshots.reset_cache()
    return jsonify({"ok": True})


@superadmin_ai_tutor_bp.post("/system-map/runtime")
def system_map_runtime():
    """Upload the result of scripts/ai_tutor_runtime_scan.mjs (run in dev/CI against a test clinic account)."""
    if request.content_length and request.content_length > MAX_RUNTIME_BYTES:
        return jsonify({"ok": False, "error": "runtime scan is too large"}), 413
    try:
        cleaned = snapshots.save_runtime(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "pages": len(cleaned["pages"]), "writes_observed": cleaned["safety"]["writes_observed"]})
