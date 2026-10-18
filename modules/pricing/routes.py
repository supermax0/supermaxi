"""Pricing API (/api/v1/desktop/pricing/*): pricing.view to read, pricing.manage to propose, pricing.approve to apply."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from extensions import db
from modules.pricing import service
from modules.pricing.models import PriceBatch, PriceHistory, PriceRule, Promotion

pricing_bp = Blueprint("pricing", __name__, url_prefix="/api/v1/desktop/pricing")


def _actor():
    from utils.permission_checks import get_current_employee

    return get_current_employee()


def _deny(permission: str):
    from utils.permission_checks import employee_can

    actor = _actor()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if not employee_can(actor, permission):
        return jsonify({"success": False, "error": "ليست لديك صلاحية هذا الإجراء في التسعير"}), 403
    return None


def _run(fn):
    try:
        out = fn()
        db.session.commit()
        return out
    except service.PricingError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), exc.status


def _audit(action: str, summary: str, payload: dict) -> None:
    try:
        from utils.activity_logger import log_activity

        log_activity(action, "pricing", summary, payload=payload, commit=False)
    except Exception:
        pass


def _rule(r: PriceRule) -> dict:
    return {"id": r.id, "scope": r.scope, "scope_value": r.scope_value or "", "target_margin_pct": r.target_margin_pct,
            "minimum_margin_pct": r.minimum_margin_pct, "extra_cost": r.extra_cost, "rounding_step": r.rounding_step,
            "automatic": r.automatic, "max_auto_change_pct": r.max_auto_change_pct,
            "approval_required": r.approval_required, "active": r.active}


@pricing_bp.get("/rules")
def rules_list():
    denied = _deny("pricing.view")
    if denied:
        return denied
    service.ensure_tables()
    return jsonify({"success": True, "rows": [_rule(r) for r in PriceRule.query.order_by(PriceRule.scope, PriceRule.id).all()]})


@pricing_bp.post("/rules")
@pricing_bp.post("/rules/<int:rule_id>")
def rules_save(rule_id: int | None = None):
    denied = _deny("pricing.manage")
    if denied:
        return denied
    actor = _actor()

    def run():
        rule = service.save_rule(request.get_json(silent=True) or {}, rule_id=rule_id, by=actor.id)
        _audit("save_rule", "حفظ قاعدة تسعير", _rule(rule))
        return jsonify({"success": True, "rule": _rule(rule)})

    return _run(run)


@pricing_bp.get("/quote/<int:product_id>")
def quote(product_id: int):
    denied = _deny("pricing.view")
    if denied:
        return denied
    service.ensure_tables()
    product = service._products().get(product_id)
    if product is None:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    return jsonify({"success": True, "quote": service.quote(product)})


@pricing_bp.post("/batches/from-rules")
def batch_rules():
    denied = _deny("pricing.manage")
    if denied:
        return denied
    actor = _actor()
    ids = (request.get_json(silent=True) or {}).get("product_ids") or None
    return _run(lambda: jsonify({"success": True, "batch": service.batch_view(service.batch_from_rules(product_ids=ids, by=actor.id))}))


@pricing_bp.post("/batches/from-file")
def batch_file():
    denied = _deny("pricing.manage")
    if denied:
        return denied
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"success": False, "error": "اختر ملف الأسعار"}), 400
    raw = upload.read(5 * 1024 * 1024 + 1)
    actor = _actor()
    supplier = str(request.form.get("supplier") or "").strip()[:80]
    return _run(lambda: jsonify({"success": True, "batch": service.batch_view(
        service.batch_from_file(raw, upload.filename or "prices", supplier_ref=supplier, by=actor.id))}))


@pricing_bp.get("/batches")
def batches_list():
    denied = _deny("pricing.view")
    if denied:
        return denied
    service.ensure_tables()
    rows = PriceBatch.query.order_by(PriceBatch.id.desc()).limit(50).all()
    return jsonify({"success": True, "rows": [{"id": b.id, "label": b.label, "source": b.source, "status": b.status,
                                               "created_at": b.created_at.isoformat()} for b in rows]})


@pricing_bp.get("/batches/<int:batch_id>")
def batch_detail(batch_id: int):
    denied = _deny("pricing.view")
    if denied:
        return denied
    batch = db.session.get(PriceBatch, batch_id)
    if batch is None:
        return jsonify({"success": False, "error": "غير موجودة"}), 404
    return jsonify({"success": True, "batch": service.batch_view(batch)})


@pricing_bp.post("/batches/<int:batch_id>/approve")
def batch_approve(batch_id: int):
    denied = _deny("pricing.approve")
    if denied:
        return denied
    actor = _actor()

    def run():
        result = service.approve(batch_id, by=actor.id)
        _audit("approve_prices", "اعتماد دفعة أسعار", {"batch_id": batch_id, **result})
        return jsonify({"success": True, "result": result})

    return _run(run)


@pricing_bp.post("/batches/<int:batch_id>/reject")
def batch_reject(batch_id: int):
    denied = _deny("pricing.approve")
    if denied:
        return denied
    actor = _actor()
    return _run(lambda: (service.reject(batch_id, by=actor.id), jsonify({"success": True}))[1])


@pricing_bp.post("/automatic/run")
def automatic_run():
    denied = _deny("pricing.approve")
    if denied:
        return denied
    actor = _actor()

    def run():
        result = service.run_automatic(by=actor.id)
        _audit("auto_prices", "تشغيل التسعير التلقائي", result)
        return jsonify({"success": True, "result": result})

    return _run(run)


@pricing_bp.get("/history")
def history():
    denied = _deny("pricing.view")
    if denied:
        return denied
    service.ensure_tables()
    query = PriceHistory.query
    if request.args.get("product_id", type=int):
        query = query.filter_by(product_id=request.args.get("product_id", type=int))
    rows = query.order_by(PriceHistory.id.desc()).limit(200).all()
    names = _product_names({h.product_id for h in rows})
    return jsonify({"success": True, "rows": [{"id": h.id, "product_id": h.product_id,
                                               "product_name": names.get(h.product_id, ""), "old_price": h.old_price,
                                               "new_price": h.new_price, "source": h.source, "reason": h.reason or "",
                                               "approved_by_id": h.approved_by_id,
                                               "at": h.created_at.isoformat()} for h in rows]})


def _product_names(ids: set) -> dict:
    from models.product import Product

    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    return {int(i): str(n or "") for i, n in Product.query.execution_options(skip_branch_scope=True)
            .filter(Product.id.in_(ids)).with_entities(Product.id, Product.name).all()}


@pricing_bp.get("/promotions")
def promotions_list():
    denied = _deny("pricing.view")
    if denied:
        return denied
    service.ensure_tables()
    service.run_due_throttled(str(getattr(g, "tenant", "")))
    rows = Promotion.query.order_by(Promotion.id.desc()).limit(100).all()
    names = _product_names({p.product_id for p in rows})
    return jsonify({"success": True, "rows": [{"id": p.id, "product_id": p.product_id,
                                               "product_name": names.get(p.product_id, ""), "promo_price": p.promo_price,
                                               "regular_price": p.regular_price, "starts_at": p.starts_at.isoformat(),
                                               "ends_at": p.ends_at.isoformat(), "status": p.status, "note": p.note or ""}
                                              for p in rows]})


@pricing_bp.post("/promotions")
def promotions_create():
    denied = _deny("pricing.approve")
    if denied:
        return denied
    actor = _actor()

    def run():
        promo = service.create_promotion(request.get_json(silent=True) or {}, by=actor.id)
        service.run_due()  # a promotion starting now takes effect immediately
        _audit("create_promotion", "إنشاء عرض بتاريخ", {"promotion_id": promo.id})
        return jsonify({"success": True, "id": promo.id, "status": promo.status})

    return _run(run)


@pricing_bp.post("/promotions/<int:promo_id>/cancel")
def promotions_cancel(promo_id: int):
    denied = _deny("pricing.approve")
    if denied:
        return denied
    return _run(lambda: jsonify({"success": True, "status": service.cancel_promotion(promo_id).status}))
