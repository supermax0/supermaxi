import json
import os
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

from extensions import db
from models.core.landing_content import (
    LandingCTA,
    LandingFAQ,
    LandingFeature,
    LandingMedia,
    LandingModule,
    LandingPageSettings,
    LandingPricingPlan,
    LandingSEO,
    LandingSection,
    LandingTestimonial,
)
from utils.landing_content import ensure_landing_seed, get_landing_payload, publish_landing


landing_bp = Blueprint("landing", __name__)

ALLOWED_MEDIA_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "svg", "mp4"}
COLLECTIONS = {
    "sections": LandingSection,
    "features": LandingFeature,
    "modules": LandingModule,
    "pricing": LandingPricingPlan,
    "faqs": LandingFAQ,
    "testimonials": LandingTestimonial,
    "ctas": LandingCTA,
    "media": LandingMedia,
}


def _is_superadmin():
    return session.get("is_superadmin") is True


def _require_superadmin_json():
    if not _is_superadmin():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return None


def _payload():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict()


def _json_text(value, default):
    if value is None:
        return json.dumps(default, ensure_ascii=False)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return json.dumps(default, ensure_ascii=False)
        try:
            parsed = json.loads(value)
            return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            return json.dumps(default, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "visible"}


def _number(value, default=0, cast=float):
    try:
        if value in (None, ""):
            return default
        return cast(value)
    except Exception:
        return default


def _apply_fields(row, data):
    editable = {
        LandingPageSettings: [
            "site_name", "page_title", "page_subtitle", "default_language", "logo_url", "favicon_url",
            "primary_color", "secondary_color", "accent_color", "background_color", "text_color",
            "font_family", "whatsapp_number", "contact_email", "login_url", "trial_url",
            "demo_booking_url", "is_active",
        ],
        LandingSEO: [
            "meta_title", "meta_description", "meta_keywords", "og_title", "og_description",
            "og_image_url", "twitter_title", "twitter_description", "twitter_image_url",
            "canonical_url", "robots", "schema_json",
        ],
        LandingSection: [
            "section_key", "section_type", "title", "subtitle", "description", "content_json",
            "image_url", "video_url", "button_primary_text", "button_primary_url", "button_secondary_text",
            "button_secondary_url", "sort_order", "is_visible", "animation_type", "background_style",
        ],
        LandingFeature: ["title", "description", "icon", "image_url", "feature_key", "sort_order", "is_visible"],
        LandingModule: ["name", "short_description", "long_description", "icon", "screenshot_url", "sort_order", "is_visible"],
        LandingPricingPlan: [
            "name", "slug", "price", "currency", "billing_period", "description", "features_json",
            "limits_json", "cta_text", "cta_url", "badge_text", "is_popular", "is_visible", "sort_order",
        ],
        LandingFAQ: ["question", "answer", "category", "sort_order", "is_visible"],
        LandingTestimonial: ["customer_name", "customer_title", "company_name", "quote", "avatar_url", "rating", "is_visible", "sort_order"],
        LandingCTA: ["label", "url", "cta_type", "placement_key", "is_visible", "sort_order"],
        LandingMedia: ["title", "media_type", "file_url", "thumbnail_url", "alt_text", "caption", "usage_key", "file_size", "mime_type", "is_active"],
    }
    model = row.__class__
    for field in editable.get(model, []):
        source_key = field
        if field == "content_json" and "content" in data:
            setattr(row, field, _json_text(data.get("content"), {}))
            continue
        if field == "features_json" and "features" in data:
            setattr(row, field, _json_text(data.get("features"), []))
            continue
        if field == "limits_json" and "limits" in data:
            setattr(row, field, _json_text(data.get("limits"), {}))
            continue
        if field == "schema_json" and "schema" in data:
            setattr(row, field, _json_text(data.get("schema"), {}))
            continue
        if source_key not in data:
            continue
        value = data.get(source_key)
        if field in {"is_active", "is_visible", "is_popular"}:
            value = _bool_value(value)
        elif field in {"sort_order", "rating", "file_size"}:
            value = _number(value, 0, int)
        elif field == "price":
            value = _number(value, 0, float)
        elif field in {"content_json", "features_json", "limits_json", "schema_json"}:
            value = _json_text(value, [] if field == "features_json" else {})
        setattr(row, field, value)
    if hasattr(row, "last_edited_by"):
        row.last_edited_by = session.get("superadmin_id")


def _model_for_collection(name):
    model = COLLECTIONS.get(name)
    if not model:
        return None
    return model


@landing_bp.route("/landing")
def public_landing():
    return render_template("landing_dynamic.html", landing=get_landing_payload("published"))


@landing_bp.route("/landing/preview")
def landing_preview():
    if not _is_superadmin():
        return render_template("superadmin_login.html"), 403
    return render_template("landing_dynamic.html", landing=get_landing_payload("draft", include_hidden=True), preview_mode=True)


@landing_bp.route("/api/landing/published")
def api_landing_published():
    return jsonify({"success": True, "data": get_landing_payload("published")})


@landing_bp.route("/superadmin/landing")
def superadmin_landing_page():
    if not _is_superadmin():
        return render_template("superadmin_login.html"), 403
    ensure_landing_seed()
    return render_template("superadmin_landing.html")


@landing_bp.route("/api/superadmin/landing", methods=["GET"])
def api_superadmin_landing():
    denied = _require_superadmin_json()
    if denied:
        return denied
    return jsonify({"success": True, "data": get_landing_payload("draft", include_hidden=True)})


@landing_bp.route("/api/superadmin/landing/settings", methods=["PUT"])
def api_update_landing_settings():
    denied = _require_superadmin_json()
    if denied:
        return denied
    data = _payload()
    row = LandingPageSettings.query.filter_by(scope="draft").first()
    if not row:
        ensure_landing_seed()
        row = LandingPageSettings.query.filter_by(scope="draft").first()
    _apply_fields(row, data)
    db.session.commit()
    return jsonify({"success": True, "item": row.to_dict()})


@landing_bp.route("/api/superadmin/landing/seo", methods=["PUT"])
def api_update_landing_seo():
    denied = _require_superadmin_json()
    if denied:
        return denied
    data = _payload()
    row = LandingSEO.query.filter_by(scope="draft").first()
    if not row:
        ensure_landing_seed()
        row = LandingSEO.query.filter_by(scope="draft").first()
    _apply_fields(row, data)
    db.session.commit()
    return jsonify({"success": True, "item": row.to_dict()})


@landing_bp.route("/api/superadmin/landing/<collection>", methods=["POST"])
def api_create_landing_item(collection):
    denied = _require_superadmin_json()
    if denied:
        return denied
    model = _model_for_collection(collection)
    if model is None or model is LandingMedia:
        return jsonify({"success": False, "error": "مجموعة غير مدعومة"}), 404
    data = _payload()
    row = model(scope="draft")
    _apply_fields(row, data)
    db.session.add(row)
    db.session.commit()
    return jsonify({"success": True, "item": row.to_dict()})


@landing_bp.route("/api/superadmin/landing/<collection>/<int:item_id>", methods=["PUT"])
def api_update_landing_item(collection, item_id):
    denied = _require_superadmin_json()
    if denied:
        return denied
    model = _model_for_collection(collection)
    if model is None:
        return jsonify({"success": False, "error": "مجموعة غير مدعومة"}), 404
    row = db.session.get(model, item_id)
    if not row or (hasattr(row, "scope") and row.scope != "draft"):
        return jsonify({"success": False, "error": "العنصر غير موجود"}), 404
    _apply_fields(row, _payload())
    db.session.commit()
    return jsonify({"success": True, "item": row.to_dict()})


@landing_bp.route("/api/superadmin/landing/<collection>/<int:item_id>", methods=["DELETE"])
def api_delete_landing_item(collection, item_id):
    denied = _require_superadmin_json()
    if denied:
        return denied
    model = _model_for_collection(collection)
    if model is None or model in {LandingPageSettings, LandingSEO}:
        return jsonify({"success": False, "error": "مجموعة غير مدعومة"}), 404
    row = db.session.get(model, item_id)
    if not row or (hasattr(row, "scope") and row.scope != "draft"):
        return jsonify({"success": False, "error": "العنصر غير موجود"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True})


@landing_bp.route("/api/superadmin/landing/media/upload", methods=["POST"])
def api_upload_landing_media():
    denied = _require_superadmin_json()
    if denied:
        return denied
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "اختر ملفاً أولاً"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_MEDIA_EXTENSIONS:
        return jsonify({"success": False, "error": "نوع الملف غير مسموح"}), 400
    safe_name = secure_filename(file.filename)
    final_name = f"{uuid4().hex}_{safe_name}"
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "landing")
    os.makedirs(upload_dir, exist_ok=True)
    full_path = os.path.join(upload_dir, final_name)
    file.save(full_path)
    url = f"/static/uploads/landing/{final_name}"
    media_type = "video" if ext == "mp4" else "image"
    row = LandingMedia(
        title=request.form.get("title") or safe_name,
        media_type=media_type,
        file_url=url,
        thumbnail_url=request.form.get("thumbnail_url") or "",
        alt_text=request.form.get("alt_text") or "",
        caption=request.form.get("caption") or "",
        usage_key=request.form.get("usage_key") or "",
        file_size=os.path.getsize(full_path),
        mime_type=file.mimetype or "",
        is_active=True,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"success": True, "item": row.to_dict()})


@landing_bp.route("/api/superadmin/landing/publish", methods=["POST"])
def api_publish_landing():
    denied = _require_superadmin_json()
    if denied:
        return denied
    data = publish_landing(session.get("superadmin_id"))
    return jsonify({"success": True, "data": data})


@landing_bp.route("/api/superadmin/landing/seed", methods=["POST"])
def api_seed_landing():
    denied = _require_superadmin_json()
    if denied:
        return denied
    created = ensure_landing_seed()
    return jsonify({"success": True, "created": created, "data": get_landing_payload("draft", include_hidden=True)})
