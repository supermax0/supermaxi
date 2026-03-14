"""
settings_api.py
---------------
API endpoints for Publisher settings (FB App credentials + page connection).
"""

from flask import Blueprint, jsonify, request, session, g

from extensions import db
from modules.publisher.models.publisher_settings import PublisherSettings
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.services import facebook_service as fb
from modules.publisher.services.token_utils import encrypt_token
import traceback
from flask import current_app

settings_api_bp = Blueprint("publisher_settings_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug") or "default"


# ── GET / SAVE App Credentials ────────────────────────────────────────────────

@settings_api_bp.route("/api/settings", methods=["GET"])
def get_settings():
    try:
        s = PublisherSettings.get(_tenant())
        return jsonify({"success": True, "settings": s.to_dict()})
    except Exception as e:
        current_app.logger.error(f"Error in get_settings: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "message": str(e)}), 500


@settings_api_bp.route("/api/settings", methods=["POST"])
def save_settings():
    """
    حفظ App ID و App Secret و User Token (اختياري).
    أي حقل فارغ = لا يُعدَّل (نبقّي القيمة القديمة).
    """
    try:
        data = request.get_json() or {}
        s = PublisherSettings.get(_tenant())

        fb_app_id     = (data.get("fb_app_id")     or "").strip()
        fb_app_secret = (data.get("fb_app_secret") or "").strip()
        fb_user_token = (data.get("fb_user_token") or "").strip()

        if fb_app_id:
            s.fb_app_id = fb_app_id
        if fb_app_secret and fb_app_secret != "●●●●●●●●":
            s.fb_app_secret = encrypt_token(fb_app_secret)
        if fb_user_token and fb_user_token != "●●●●●●●●":
            s.fb_user_token = encrypt_token(fb_user_token)

        db.session.commit()
        return jsonify({"success": True, "message": "تم حفظ الإعدادات بنجاح"})
    except Exception as e:
        current_app.logger.error(f"Error in save_settings: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "message": str(e)}), 500


# ── Connect Pages (جلب صفحات الفيسبوك) ───────────────────────────────────────

@settings_api_bp.route("/api/settings/connect-pages", methods=["POST"])
def connect_pages():
    """
    جلب الصفحات باستخدام الـ User Token المحفوظ أو الـ Token المُرسَل في الطلب.
    """
    from modules.publisher.services.token_utils import decrypt_token

    try:
        data = request.get_json() or {}
        tenant = _tenant()
        s = PublisherSettings.get(tenant)

        # أولوية: token في الطلب ← token المحفوظ في الإعدادات
        raw_token = (data.get("user_token") or "").strip()
        if not raw_token:
            if s.fb_user_token:
                try:
                    raw_token = decrypt_token(s.fb_user_token)
                except Exception:
                    raw_token = s.fb_user_token
            else:
                return jsonify({"success": False,
                                "message": "أدخل User Token أولاً في الإعدادات"}), 400

        result = fb.get_user_pages(raw_token)
        if not result.get("success"):
            return jsonify(result), 400

        pages_data = result.get("pages", [])
        saved = []
        for page in pages_data:
            page_id    = page.get("id")
            page_name  = page.get("name", "")
            page_token = page.get("access_token", "")
            if not page_id or not page_token:
                continue

            existing = PublisherPage.query.filter_by(
                tenant_slug=tenant, page_id=page_id
            ).first()
            if existing:
                existing.page_name  = page_name
                existing.page_token = encrypt_token(page_token)
            else:
                db.session.add(PublisherPage(
                    tenant_slug=tenant,
                    page_id=page_id,
                    page_name=page_name,
                    page_token=encrypt_token(page_token),
                ))
            saved.append({"page_id": page_id, "page_name": page_name})

        db.session.commit()
        return jsonify({
            "success": True,
            "message": f"تم ربط {len(saved)} صفحة بنجاح",
            "pages":   saved,
        })
    except Exception as e:
        current_app.logger.error(f"Error in connect_pages: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "message": str(e)}), 500
