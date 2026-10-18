"""Search administration: company synonyms and an «explain» probe (/api/v1/desktop/search/*)."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from extensions import db
from modules.search import engine

search_admin_bp = Blueprint("search_admin", __name__, url_prefix="/api/v1/desktop/search")


def _deny():
    from utils.permission_checks import employee_can, get_current_employee

    actor = get_current_employee()
    if actor is None:
        return jsonify({"success": False, "error": "سجّل الدخول"}), 401
    if not employee_can(actor, "manage_inventory"):
        return jsonify({"success": False, "error": "ليست لديك صلاحية إعداد البحث"}), 403
    return None


@search_admin_bp.get("/synonyms")
def synonyms_get():
    denied = _deny()
    if denied:
        return denied
    return jsonify({"success": True, "synonyms": engine.company_synonyms()})


@search_admin_bp.post("/synonyms")
def synonyms_save():
    """{"synonyms": {"كاونتر": "ثلاجة", …}} replaces the company list (max 500 pairs)."""
    denied = _deny()
    if denied:
        return denied
    from models.system_settings import SystemSettings

    raw = (request.get_json(silent=True) or {}).get("synonyms")
    if not isinstance(raw, dict) or len(raw) > 500:
        return jsonify({"success": False, "error": "قائمة غير صالحة (حتى 500 كلمة)"}), 400
    clean = {str(k).strip()[:40]: str(v).strip()[:60] for k, v in raw.items() if str(k).strip() and str(v).strip()}
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["search_synonyms"] = clean
    settings.set_ui_flags(flags)
    db.session.commit()
    engine.invalidate(str(getattr(g, "tenant", "") or ""))
    return jsonify({"success": True, "synonyms": clean})


@search_admin_bp.get("/explain")
def explain():
    """What the engine understands from a phrase and which products it returns first (for tuning)."""
    denied = _deny()
    if denied:
        return denied
    q = str(request.args.get("q") or "")[:120]
    slug = str(getattr(g, "tenant", "") or "")
    result = engine.search(slug, q, synonyms=engine.company_synonyms())
    docs = engine.doc_map(slug)
    return jsonify({"success": True, **engine.to_dict(result),
                    "top": [{"id": i, "name": docs[i].name, "price": docs[i].price, "in_stock": docs[i].in_stock,
                             "score": round(engine.score(docs[i], result.intent), 3)} for i in result.ids[:10] if i in docs]})
