"""Isolated HTTP bridge to real audit services and a disposable tenant database.

Authentication is a test fixture. Audit views, permissions, SQLite transactions,
reports and stock posting use the actual application implementation.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server

spec = importlib.util.spec_from_file_location("audit_test_fixture", ROOT / "tests/test_smart_inventory_audit.py")
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
fixture = fixture_module.audit_workspace.__wrapped__()
workspace = next(fixture)
from modules.inventory_audit.common import PERMISSIONS
from modules.inventory_audit.models import InventoryCountSession, InventoryCountEvent
from models.journal_entry import JournalEntry
from modules.finance.models import FinanceVoucher
from models.account_transaction import AccountTransaction

proxy = Flask("finora-audit-integration-fixture")
admin = workspace["admin"]
session_data = {
    "user": {"id": admin.id, "name": admin.name, "username": admin.username, "role": "admin"},
    "tenant": {"id": admin.tenant_id, "slug": workspace["tenant"], "name": "شركة اختبار الجرد", "business_type": "retail"},
    "branch": {"id": workspace["branches"][0].id, "name": workspace["branches"][0].name},
    "branch_scope": "all", "roles": ["admin"], "session_max_age_seconds": 86400,
    "permissions": [*PERMISSIONS, "can_manage_inventory", "edit_current_stock", "finance.approve", "can_see_orders", "can_manage_suppliers"],
}

@proxy.route("/api/v1/desktop/auth/<action>", methods=["GET", "POST"])
def auth(action):
    if action == "session" and request.cookies.get("session") != "isolated-audit-test":
        return jsonify(ok=False, code="unauthenticated", error="Test login required"), 401
    response = jsonify(ok=True, session=session_data)
    response.set_cookie("session", "isolated-audit-test", httponly=True, samesite="Lax", max_age=86400)
    return response

@proxy.route("/api/v1/desktop/inventory-audits", defaults={"suffix": ""}, methods=["GET", "POST"])
@proxy.route("/api/v1/desktop/inventory-audits/<path:suffix>", methods=["GET", "POST"])
def audit(suffix):
    if suffix.startswith("local/"):
        return jsonify(success=False, error="Native-only storage"), 404
    full_path = request.full_path.rstrip("?")
    return workspace["call"](full_path, request.get_json() if request.method == "POST" else None)


@proxy.get("/api/v1/desktop/inventory-activity", defaults={"suffix": ""})
@proxy.get("/api/v1/desktop/inventory-activity/<path:suffix>")
@proxy.get("/inventory/<path:suffix>")
@proxy.get("/purchases/<path:suffix>")
def stock_activity(suffix):
    return workspace["call"](request.full_path.rstrip("?"))


@proxy.post("/__audit_test/seed-stock-history")
def seed_stock_history():
    """Actual credit purchase receipts; no interception of inventory reads."""
    from app import app
    from flask import g, session
    from models.supplier import Supplier
    from routes.purchases import _create_purchase_from_payload
    with app.test_request_context("/purchases", method="POST"):
        g.tenant = workspace["tenant"]
        session.update(user_id=admin.id, role=admin.role, tenant_slug=workspace["tenant"])
        g.branch, g.branches = workspace["branches"][0], workspace["branches"]
        g.view_all_branches, g.independent_branches_enabled, g.branch_scope_ready = True, True, True
        supplier = Supplier(name="مورد اختبار الحركة", branch_id=workspace["branches"][0].id)
        workspace["db"].session.add(supplier)
        workspace["db"].session.flush()
        ids = []
        for number in range(28):
            purchase, error = _create_purchase_from_payload({
                "supplier_id": supplier.id, "_validated_branch_id": workspace["branches"][0].id,
                "invoice_no": f"ACT-{number + 1:03}", "status": "confirmed", "purchase_mode": "credit",
                "items": [{"product_id": workspace["products"][0].id, "quantity": 1, "unit_cost_before_discount": 100}],
            }, [], employee_id=admin.id)
            if error:
                raise RuntimeError(error)
            ids.append(purchase.id)
        workspace["db"].session.commit()
    return jsonify(ok=True, purchases=ids)

@proxy.get("/__audit_test/state")
def state():
    from app import app
    from flask import g
    from models.branch import BranchStock
    with app.app_context():
        g.tenant = workspace["tenant"]
        return jsonify(
            stocks=[workspace["db"].session.get(BranchStock, row.id).quantity for row in workspace["stocks"]],
            sessions=[{"id": row.id, "status": row.status} for row in InventoryCountSession.query.all()],
            events=InventoryCountEvent.query.count(),
            journals=JournalEntry.query.filter_by(reference_type="inventory_count").count(),
            cash=AccountTransaction.query.count(), vouchers=FinanceVoucher.query.count(),
        )


@proxy.post("/__audit_test/seed-cost-basis")
def seed_cost_basis():
    from app import app
    from flask import g
    from models.inventory_lot import InventoryLot
    with app.app_context():
        g.tenant = workspace["tenant"]
        workspace["db"].session.add(InventoryLot(product_id=workspace["products"][0].id,
            branch_id=workspace["branches"][0].id, quantity=17, remaining_quantity=17, unit_cost=100))
        workspace["db"].session.commit()
    return jsonify(ok=True)

@proxy.get("/inventory/smart-audit")
def audit_web():
    return send_from_directory(ROOT / "static/finora-inventory-audit", "audit.html")

@proxy.get("/static/finora-inventory-audit/<path:filename>")
def assets(filename):
    return send_from_directory(ROOT / "static/finora-inventory-audit", filename)

server = make_server("127.0.0.1", 0, proxy, threaded=False)
@proxy.post("/__audit_test/shutdown")
def shutdown():
    from threading import Thread
    Thread(target=server.shutdown, daemon=True).start()
    return jsonify(ok=True)

print(json.dumps({"ready": True, "url": f"http://127.0.0.1:{server.server_port}", "tenant": workspace["tenant"]}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    # Finish the fixture normally so its post-yield tenant cleanup runs.
    next(fixture, None)
