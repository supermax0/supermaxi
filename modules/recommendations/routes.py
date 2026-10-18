"""Recommendation administration (/api/v1/desktop/recommendations/*): manage_inventory to read and curate."""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from extensions import db
from modules.recommendations import service
from modules.recommendations.models import Bundle, ProductRelation

recommendations_bp = Blueprint("recommendations_admin", __name__, url_prefix="/api/v1/desktop/recommendations")


def _actor():
    from utils.permission_checks import get_current_employee

    return get_current_employee()


def _deny(permission: str = "manage_inventory"):
    from utils.permission_checks import employee_can

    actor = _actor()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if not employee_can(actor, permission):
        return jsonify({"success": False, "error": "ليست لديك صلاحية إدارة التوصيات"}), 403
    return None


def _run(fn):
    try:
        out = fn()
        db.session.commit()
        return out
    except LookupError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


def _audit(action: str, summary: str, payload: dict) -> None:
    try:
        from utils.activity_logger import log_activity

        log_activity(action, "recommendations", summary, payload=payload, commit=False)
    except Exception:
        pass


def _relation(r: ProductRelation, names: dict[int, str]) -> dict:
    return {"id": r.id, "source_product_id": r.source_product_id, "source_name": names.get(r.source_product_id, ""),
            "target_product_id": r.target_product_id, "target_name": names.get(r.target_product_id, ""),
            "relation_type": r.relation_type, "compatibility_note": r.compatibility_note or "",
            "priority": r.priority, "verified": bool(r.verified)}


def _names(ids: set[int]) -> dict[int, str]:
    from models.product import Product

    if not ids:
        return {}
    rows = (Product.query.execution_options(skip_branch_scope=True).filter(Product.id.in_(ids))
            .with_entities(Product.id, Product.name).all())
    return {int(i): str(n or "") for i, n in rows}


@recommendations_bp.get("/relations")
def relations_list():
    denied = _deny()
    if denied:
        return denied
    service.ensure_tables()
    q = ProductRelation.query
    product_id = request.args.get("product_id", type=int)
    if product_id:
        q = q.filter((ProductRelation.source_product_id == product_id) | (ProductRelation.target_product_id == product_id))
    rows = q.order_by(ProductRelation.source_product_id, ProductRelation.priority, ProductRelation.id).limit(500).all()
    names = _names({r.source_product_id for r in rows} | {r.target_product_id for r in rows})
    return jsonify({"success": True, "rows": [_relation(r, names) for r in rows]})


@recommendations_bp.post("/relations")
def relations_save():
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    actor = _actor()

    def go():
        row = service.save_relation(data, by=getattr(actor, "id", None))
        _audit("recommendation_relation_saved", f"علاقة منتج {row.source_product_id} → {row.target_product_id}",
               {"id": row.id, "type": row.relation_type, "verified": row.verified})
        return jsonify({"success": True, "relation": _relation(row, _names({row.source_product_id, row.target_product_id}))})

    return _run(go)


@recommendations_bp.post("/relations/<int:relation_id>/delete")
def relations_delete(relation_id: int):
    denied = _deny()
    if denied:
        return denied
    service.ensure_tables()
    row = db.session.get(ProductRelation, relation_id)
    if row is None:
        return jsonify({"success": False, "error": "العلاقة غير موجودة"}), 404
    _audit("recommendation_relation_deleted", f"حذف علاقة {row.source_product_id} → {row.target_product_id}",
           {"id": row.id})
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True})


def _bundle(b: Bundle) -> dict:
    ids = json.loads(b.product_ids_json or "[]")
    return {"id": b.id, "title": b.title, "description": b.description or "", "product_ids": ids,
            "active": bool(b.active), "products": [{"id": i, "name": n} for i, n in _names(set(ids)).items()]}


@recommendations_bp.get("/bundles")
def bundles_list():
    denied = _deny()
    if denied:
        return denied
    service.ensure_tables()
    return jsonify({"success": True, "rows": [_bundle(b) for b in Bundle.query.order_by(Bundle.sort_order, Bundle.id).all()]})


@recommendations_bp.post("/bundles")
@recommendations_bp.post("/bundles/<int:bundle_id>")
def bundles_save(bundle_id: int | None = None):
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}

    def go():
        b = service.save_bundle(data, bundle_id=bundle_id)
        _audit("recommendation_bundle_saved", f"باقة: {b.title}", {"id": b.id, "active": b.active})
        return jsonify({"success": True, "bundle": _bundle(b)})

    return _run(go)


@recommendations_bp.get("/preview/<int:product_id>")
def preview(product_id: int):
    """What a shopper would see on this product's page — so staff can check before relying on it."""
    denied = _deny()
    if denied:
        return denied
    from flask import g

    slug = str(getattr(g, "tenant", "") or "")
    recs = service.for_product(slug, product_id)
    ids = {a["id"] for a in recs["accessories"]} | set(recs["bought_together"]) | {u["id"] for u in recs["upgrades"]} | set(recs["similar"])
    return jsonify({"success": True, **recs, "names": {str(k): v for k, v in _names(ids).items()}})
