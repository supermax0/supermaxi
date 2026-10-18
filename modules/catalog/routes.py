"""Catalogue administration JSON API (/api/v1/desktop/catalog/*) and the POS level-3 catalogue search."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from extensions import db
from modules.catalog import service
from modules.catalog.models import AvailabilityRequest, CatalogProduct

catalog_admin_bp = Blueprint("catalog_admin", __name__, url_prefix="/api/v1/desktop/catalog")


def _actor():
    from utils.permission_checks import get_current_employee

    return get_current_employee()


def _deny(permission: str = "manage_inventory", *, admin_only: bool = False, need_flag: bool = True):
    from utils.permission_checks import employee_can

    actor = _actor()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if admin_only and actor.role != "admin":
        return jsonify({"success": False, "error": "للمدير العام فقط"}), 403
    if not admin_only and not employee_can(actor, permission):
        return jsonify({"success": False, "error": "ليست لديك صلاحية إدارة الكتالوج"}), 403
    if need_flag and not service.enabled():
        return jsonify({"success": False, "error": "الكتالوج الرئيسي غير مفعّل لهذه الشركة", "code": "disabled"}), 409
    return None


def _run(fn):
    try:
        result = fn()
        db.session.commit()
        return result
    except service.CatalogError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc), "code": exc.code, **exc.extra}), exc.status


@catalog_admin_bp.get("/settings")
def catalog_settings():
    denied = _deny(admin_only=True, need_flag=False)
    if denied:
        return denied
    from models.system_settings import SystemSettings

    flags = SystemSettings.get_settings().get_ui_flags()
    return jsonify({"success": True, "catalog_layer": bool(flags.get(service.FLAG)),
                    "pos_catalog_search": bool(flags.get("pos_catalog_search"))})


@catalog_admin_bp.post("/settings")
def catalog_settings_save():
    """Turning the layer on creates its (empty) tables; turning it off hides it — nothing is deleted."""
    denied = _deny(admin_only=True, need_flag=False)
    if denied:
        return denied
    from models.system_settings import SystemSettings

    data = request.get_json(silent=True) or {}
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    for key in (service.FLAG, "pos_catalog_search"):
        if key in data:
            flags[key] = bool(data[key])
    if flags.get(service.FLAG):
        service.ensure_tables()
    settings.set_ui_flags(flags)
    db.session.commit()
    return jsonify({"success": True, "catalog_layer": bool(flags.get(service.FLAG)),
                    "pos_catalog_search": bool(flags.get("pos_catalog_search"))})


@catalog_admin_bp.get("/entries")
def entries_list():
    denied = _deny()
    if denied:
        return denied
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = service.search(request.args.get("q", ""), limit=30, offset=(page - 1) * 30)
    return jsonify({"success": True, "rows": [service.serialize(r) for r in rows], "total": total, "page": page})


@catalog_admin_bp.get("/entries/<int:entry_id>")
def entry_detail(entry_id: int):
    denied = _deny()
    if denied:
        return denied
    entry = db.session.get(CatalogProduct, entry_id)
    if entry is None:
        return jsonify({"success": False, "error": "غير موجود"}), 404
    return jsonify({"success": True, "entry": service.serialize(entry)})


@catalog_admin_bp.post("/entries")
@catalog_admin_bp.post("/entries/<int:entry_id>")
def entry_save(entry_id: int | None = None):
    denied = _deny()
    if denied:
        return denied
    actor = _actor()
    return _run(lambda: jsonify({"success": True, "entry": service.serialize(
        service.save_entry(request.get_json(silent=True) or {}, by=actor.id, entry_id=entry_id))}))


@catalog_admin_bp.post("/entries/<int:entry_id>/listing")
def entry_listing(entry_id: int):
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}

    def run():
        service.set_listing(entry_id, publish=bool(data.get("publish")), policy=str(data.get("policy") or "request"),
                            featured=bool(data.get("featured")))
        return jsonify({"success": True, "entry": service.serialize(db.session.get(CatalogProduct, entry_id))})

    return _run(run)


@catalog_admin_bp.post("/entries/<int:entry_id>/activate")
def entry_activate(entry_id: int):
    """Explicit activation into FINORA Inventory (quantity 0). The POS shows it only if ``pos_visible`` is set."""
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    actor = _actor()
    return _run(lambda: jsonify({"success": True, "product_id": service.activate(
        entry_id, sale_price=int(data.get("sale_price") or 0), pos_visible=bool(data.get("pos_visible")),
        by=actor.id)}))


@catalog_admin_bp.post("/entries/<int:entry_id>/link")
def entry_link(entry_id: int):
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}

    def run():
        service.link(entry_id, int(data.get("product_id") or 0))
        return jsonify({"success": True})

    return _run(run)


@catalog_admin_bp.get("/requests")
def availability_requests():
    denied = _deny()
    if denied:
        return denied
    service.ensure_tables()
    rows = AvailabilityRequest.query.order_by(AvailabilityRequest.id.desc()).limit(200).all()
    names = {e.id: e.canonical_name for e in CatalogProduct.query.filter(
        CatalogProduct.id.in_([r.catalog_product_id for r in rows] or [0])).all()}
    return jsonify({"success": True, "rows": [{
        "id": r.id, "product": names.get(r.catalog_product_id, ""), "catalog_product_id": r.catalog_product_id,
        "customer_name": r.customer_name, "phone": r.phone, "city": r.city or "", "note": r.note or "",
        "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else ""} for r in rows]})


@catalog_admin_bp.get("/pos-search")
def pos_catalog_search():
    """POS search level 3: models in the catalogue the branch does not sell yet. Read-only, never sellable here."""
    from utils.permission_checks import employee_can

    actor = _actor()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if not employee_can(actor, "view_pos"):
        return jsonify({"success": False, "error": "ليست لديك صلاحية نقطة البيع"}), 403
    from models.system_settings import SystemSettings

    flags = SystemSettings.get_settings().get_ui_flags()
    if not (flags.get(service.FLAG) and flags.get("pos_catalog_search")):
        return jsonify({"success": False, "error": "البحث في الكتالوج الكامل غير مفعّل", "code": "disabled"}), 409
    rows, _ = service.search(request.args.get("q", ""), limit=15)
    return jsonify({"success": True, "rows": [{
        "kind": "catalog", "sellable": False, "id": r.id, "name": r.canonical_name, "brand": r.brand or "",
        "model": r.model_number or "", "note": "موجود في الكتالوج وغير مفعّل في المخزون"} for r in rows]})


# ───────────────────────────── smart add (Sprint 4) ─────────────────────────────


@catalog_admin_bp.get("/lookup")
def catalog_lookup():
    """Barcode / model → what the catalogue, the inventory and the configured sources already know."""
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import importer

    try:
        return jsonify({"success": True, **importer.lookup(request.args.get("q", ""))})
    except service.CatalogError as exc:
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), exc.status


@catalog_admin_bp.post("/imports")
def import_upload():
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import importer

    upload = request.files.get("file")
    if upload is None:
        return jsonify({"success": False, "error": "اختر ملف Excel أو CSV"}), 400
    raw = upload.read(importer.MAX_BYTES + 1)
    actor = _actor()
    return _run(lambda: jsonify({"success": True, "batch": importer.batch_view(
        importer.create_batch(raw, upload.filename or "upload", by=actor.id))}))


@catalog_admin_bp.get("/imports/<int:batch_id>")
def import_view(batch_id: int):
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import importer
    from modules.catalog.models import CatalogImportBatch

    batch = db.session.get(CatalogImportBatch, batch_id)
    if batch is None:
        return jsonify({"success": False, "error": "غير موجودة"}), 404
    return jsonify({"success": True, "batch": importer.batch_view(batch)})


@catalog_admin_bp.post("/imports/<int:batch_id>/apply")
def import_apply(batch_id: int):
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import importer

    actor = _actor()
    data = request.get_json(silent=True) or {}
    return _run(lambda: jsonify({"success": True, "result": importer.apply(
        batch_id, by=actor.id, include_review=bool(data.get("include_review")))}))


@catalog_admin_bp.post("/entries/<int:entry_id>/media")
def media_upload(entry_id: int):
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import images

    upload = request.files.get("file")
    if upload is None:
        return jsonify({"success": False, "error": "اختر صورة"}), 400
    raw = upload.read(images.MAX_BYTES + 1)

    def run():
        images.save_upload(entry_id, raw, role=request.form.get("role", ""), rights=request.form.get("rights", "own_photo"))
        return jsonify({"success": True, "entry": service.serialize(db.session.get(CatalogProduct, entry_id))})

    return _run(run)


@catalog_admin_bp.post("/entries/<int:entry_id>/media/<int:media_id>/<action>")
def media_action(entry_id: int, media_id: int, action: str):
    denied = _deny()
    if denied:
        return denied
    from modules.catalog import images

    def run():
        if action == "remove":
            images.remove(entry_id, media_id)
        elif action in ("verify", "unverify"):
            images.verify(entry_id, media_id, action == "verify")
        else:
            raise service.CatalogError("إجراء غير معروف")
        return jsonify({"success": True, "entry": service.serialize(db.session.get(CatalogProduct, entry_id))})

    return _run(run)
