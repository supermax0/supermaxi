"""Immutable, permission-scoped export pages for resumable desktop downloads.

Read collections are captured during a recorded interval. They are display data,
not stock reservations or permission to finalize an offline financial operation.
"""
from __future__ import annotations

import hashlib
import json
import time
from uuid import UUID

from flask import abort, current_app, g, jsonify, request, session
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.desktop_api.routes import DESKTOP_PERMISSIONS, desktop_api_bp
from utils.permission_checks import employee_can, get_current_employee

PAGE_SIZE = 100
MAX_RECORDS = 50000
LIFETIME_MS = 24 * 60 * 60 * 1000


class DesktopSnapshot(db.Model):
    __tablename__ = "desktop_snapshot"
    id = db.Column(db.String(36), primary_key=True)
    device_id = db.Column(db.String(36), nullable=False, index=True)
    scope = db.Column(db.Text, nullable=False)
    expires = db.Column(db.BigInteger, nullable=False, index=True)
    manifest = db.Column(db.Text, nullable=False)


class DesktopSnapshotPage(db.Model):
    __tablename__ = "desktop_snapshot_page"
    __table_args__ = (db.UniqueConstraint("snapshot_id", "dataset", "cursor", name="_desktop_snapshot_page_uc"),)
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.String(36), nullable=False, index=True)
    dataset = db.Column(db.String(40), nullable=False)
    cursor = db.Column(db.Integer, nullable=False)
    rows_json = db.Column(db.Text, nullable=False)
    digest = db.Column(db.String(64), nullable=False)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _scope():
    from utils.branch_context import current_branch_id, init_branch_context
    from utils.branch_migration import get_default_branch
    employee = get_current_employee()
    if not session.get("user_id") or not employee:
        abort(401)
    init_branch_context()
    branch_id = current_branch_id()
    if not branch_id:
        branch = get_default_branch()
        branch_id = branch.id if branch else None
    return {
        "tenant_slug": session.get("tenant_slug"), "user_id": employee.id, "branch_id": branch_id,
        "branch_scope": "shared" if not getattr(g, "independent_branches_enabled", True)
        else "all" if getattr(g, "view_all_branches", False) else "branch",
        "permissions": sorted(p for p in DESKTOP_PERMISSIONS if employee_can(employee, p)),
        "role": employee.role,
        "roles": sorted(role.name for role in (employee.roles or [])),
    }


def _schema():
    connection = db.session.connection()
    DesktopSnapshot.__table__.create(bind=connection, checkfirst=True)
    DesktopSnapshotPage.__table__.create(bind=connection, checkfirst=True)


def _response(value):
    response = current_app.make_response(value)
    if response.status_code != 200:
        abort(response)
    body = response.get_json()
    if not isinstance(body, (dict, list)) or isinstance(body, dict) and body.get("success") is False:
        abort(500)
    return body


def _collections(scope):
    """Use native adapters, including their account rules and access checks."""
    permissions = set(scope["permissions"])
    result = []

    def page(name, response):
        body = _response(response)
        rows = body["rows"]
        if len(rows) != body["total"]:
            abort(503, description="لم تكتمل مجموعة البيانات؛ أعد التنزيل")
        result.append((name, rows, {k: v for k, v in body.items() if k not in {"rows", "page", "page_size", "total", "total_pages"}}))
        return rows

    def values(name, rows):
        result.append((name, rows, {}))

    if "can_manage_inventory" in permissions:
        from routes.inventory import products_api, product_api_details
        from routes.purchases import purchases_page_api, get_purchase_one, search_products_for_purchase
        products = page("products", products_api(_snapshot=True))
        values("purchase-products", _response(search_products_for_purchase(_snapshot=True)))
        values("product-details", [{"id": row["id"], "value": _response(product_api_details(row["id"]))} for row in products])
        purchases = page("purchases", purchases_page_api(_snapshot=True))
        values("purchase-details", [{"id": row["id"], "value": _response(get_purchase_one(row["id"]))} for row in purchases])
    if "can_manage_suppliers" in permissions:
        from routes.suppliers import (_suppliers_schema_guard, management_suppliers_page,
                                      management_supplier_details, management_supplier_sale_products)
        _suppliers_schema_guard()
        suppliers = page("suppliers", management_suppliers_page(_snapshot=True))
        values("supplier-details", [{"id": row["id"], "value": _response(management_supplier_details(row["id"]))} for row in suppliers])
        values("supplier-products", _response(management_supplier_sale_products(_snapshot=True)))
    if "can_see_orders" in permissions:
        from routes.orders import orders_data, orders_api_lookups, orders_api_counts, details, _orders_data_query
        from models.invoice import Invoice
        orders = page("orders", orders_data(_snapshot=True))
        counts = _response(orders_api_counts())
        memberships = {tab: {entry[0] for entry in _orders_data_query(tab).with_entities(Invoice.id).all()}
                       for tab in counts["counts"]}
        for row in orders:
            row["_offline_tabs"] = [tab for tab, ids in memberships.items() if row["id"] in ids]
        values("order-details", [{"id": row["id"], "value": _response(details(row["id"]))} for row in orders])
        values("order-lookups", [{"id": 0, "value": _response(orders_api_lookups())}])
        values("order-counts", [{"id": 0, "value": counts}])
    if "view_pos" in permissions:
        from routes.pos import pos_api_products, pos_api_bootstrap
        from services.pos_catalog import search_pos_customers
        page("pos-products", pos_api_products(_snapshot=True))
        values("pos-bootstrap", [{"id": 0, "value": _response(pos_api_bootstrap())}])
        values("customers", search_pos_customers(get_current_employee(), "", branch_id=scope["branch_id"], _snapshot=True))
        if "pay_orders" in permissions:
            from routes.orders import payment_accounts
            values("payment-accounts", [{"id": 0, "value": _response(payment_accounts())}])
    if any(len(rows) > MAX_RECORDS for _, rows, _ in result):
        abort(413, description="مجموعة بيانات تتجاوز حد النسخة المحلية الحالية (50000)")
    return result


def _checked_snapshot(snapshot_id, scope):
    snapshot = db.session.get(DesktopSnapshot, snapshot_id)
    if not snapshot:
        abort(404)
    if snapshot.scope != _json(scope):
        abort(403, description="تغيّر المستخدم أو الفرع أو الصلاحيات منذ إنشاء النسخة")
    if snapshot.expires <= int(time.time() * 1000):
        abort(410, description="انتهت نسخة التنزيل؛ ابدأ نسخة جديدة")
    return snapshot


@desktop_api_bp.post("/snapshots")
def create_snapshot():
    scope = _scope()
    if request.args:
        abort(400)
    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict) or set(body) != {"id", "device_id"}:
            raise ValueError()
        snapshot_id, device_id = str(UUID(str(body["id"]))), str(UUID(str(body["device_id"])))
    except (ValueError, KeyError, TypeError, AttributeError):
        return jsonify(success=False, error="معرّفات التنزيل غير صحيحة"), 400
    _schema()
    existing = db.session.get(DesktopSnapshot, snapshot_id)
    if existing:
        snapshot = _checked_snapshot(snapshot_id, scope)
        if snapshot.device_id != device_id:
            abort(403)
        return jsonify(json.loads(snapshot.manifest))
    started = int(time.time() * 1000)
    collections = _collections(scope)
    if _scope() != scope:
        abort(409, description="تغيّرت صلاحيات النسخة أثناء التنزيل")
    captured = int(time.time() * 1000)
    manifest = {"success": True, "version": 1, "id": snapshot_id, **scope, "started_at": started,
                "captured_at": captured, "expires_at": captured + LIFETIME_MS, "datasets": []}
    pages = []
    for name, rows, meta in collections:
        manifest["datasets"].append({"name": name, "total": len(rows), "page_size": PAGE_SIZE, "meta": meta})
        for cursor in range(0, len(rows), PAGE_SIZE):
            rows_json = _json(rows[cursor:cursor + PAGE_SIZE])
            if len(rows_json.encode()) > 8 * 1024 * 1024:
                abort(413, description="صفحة تنزيل تتجاوز الحجم المسموح")
            pages.append(DesktopSnapshotPage(snapshot_id=snapshot_id, dataset=name, cursor=cursor,
                                            rows_json=rows_json, digest=hashlib.sha256(rows_json.encode()).hexdigest()))
    # Repair/schema work in native read adapters finishes before storing this immutable generation.
    _schema()
    expired_ids = [row.id for row in DesktopSnapshot.query.filter(DesktopSnapshot.expires <= captured).all()]
    if expired_ids:
        DesktopSnapshotPage.query.filter(DesktopSnapshotPage.snapshot_id.in_(expired_ids)).delete(synchronize_session=False)
        DesktopSnapshot.query.filter(DesktopSnapshot.id.in_(expired_ids)).delete(synchronize_session=False)
    db.session.add(DesktopSnapshot(id=snapshot_id, device_id=device_id, scope=_json(scope),
                                   expires=manifest["expires_at"], manifest=_json(manifest)))
    db.session.add_all(pages)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = _checked_snapshot(snapshot_id, scope)
        if existing.device_id != device_id:
            abort(403)
        return jsonify(json.loads(existing.manifest))
    return jsonify(manifest)


@desktop_api_bp.get("/snapshots/<uuid:snapshot_id>/<dataset>")
def snapshot_page(snapshot_id, dataset):
    scope = _scope()
    _schema()
    snapshot = _checked_snapshot(str(snapshot_id), scope)
    manifest = json.loads(snapshot.manifest)
    definition = next((entry for entry in manifest["datasets"] if entry["name"] == dataset), None)
    cursor = request.args.get("cursor", type=int)
    if not definition or cursor is None or cursor < 0 or cursor % PAGE_SIZE or cursor >= definition["total"]:
        abort(400)
    page = DesktopSnapshotPage.query.filter_by(snapshot_id=snapshot.id, dataset=dataset, cursor=cursor).one()
    next_cursor = cursor + min(PAGE_SIZE, definition["total"] - cursor)
    return jsonify(success=True, id=snapshot.id, dataset=dataset, cursor=cursor,
                   next_cursor=next_cursor, rows_json=page.rows_json, digest=page.digest)
