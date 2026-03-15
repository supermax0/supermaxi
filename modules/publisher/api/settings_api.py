"""
settings_api.py
---------------
API endpoints for Publisher settings (FB App credentials + page connection).
"""

from flask import Blueprint, request, session, g

from extensions import db
from modules.publisher.api.response_utils import error_response, ok_response
from modules.publisher.models.publisher_settings import PublisherSettings
from modules.publisher.services.page_connect_service import connect_and_store_pages
from modules.publisher.services.schema_guard import ensure_publisher_schema
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
        # Force schema sync here to avoid transient 500 when new settings columns are deployed.
        ensure_publisher_schema(force=True)
        s = PublisherSettings.get(_tenant())
        payload = s.to_dict()
        return ok_response(data=payload, legacy={"settings": payload})
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="settings_get_failed",
            message=str(exc),
            status_code=500,
        )


@settings_api_bp.route("/api/settings", methods=["POST"])
def save_settings():
    """
    حفظ App ID و App Secret و User Token و OpenAI API Key (اختياري).
    أي حقل فارغ = لا يُعدَّل (نبقّي القيمة القديمة).
    """
    try:
        # Force schema sync to ensure settings fields are available before query/commit.
        ensure_publisher_schema(force=True)
        data = request.get_json() or {}
        s = PublisherSettings.get(_tenant())

        fb_app_id     = (data.get("fb_app_id")     or "").strip()
        fb_app_secret = (data.get("fb_app_secret") or "").strip()
        fb_user_token = (data.get("fb_user_token") or "").strip()
        openai_api_key = (data.get("openai_api_key") or "").strip()

        if fb_app_id:
            s.fb_app_id = fb_app_id
        if fb_app_secret and fb_app_secret != "●●●●●●●●":
            s.fb_app_secret = encrypt_token(fb_app_secret)
        if fb_user_token and fb_user_token != "●●●●●●●●":
            s.fb_user_token = encrypt_token(fb_user_token)
        if openai_api_key and openai_api_key != "●●●●●●●●":
            s.openai_api_key = encrypt_token(openai_api_key)

        db.session.commit()
        return ok_response(
            data=s.to_dict(),
            message="تم حفظ الإعدادات بنجاح",
            legacy={"settings": s.to_dict()},
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="settings_save_failed",
            message=str(exc),
            status_code=500,
        )


# ── Connect Pages (جلب صفحات الفيسبوك) ───────────────────────────────────────

@settings_api_bp.route("/api/settings/connect-pages", methods=["POST"])
def connect_pages():
    """
    جلب الصفحات باستخدام الـ User Token المحفوظ أو الـ Token المُرسَل في الطلب.
    """
    from modules.publisher.services.token_utils import decrypt_token

    try:
        # Force schema sync because this endpoint reads PublisherSettings too.
        ensure_publisher_schema(force=True)
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
                return error_response(
                    code="missing_user_token",
                    message="أدخل User Token أولاً في الإعدادات",
                    status_code=400,
                )

        result = connect_and_store_pages(tenant_slug=tenant, user_token=raw_token)
        if not result.get("success"):
            return error_response(
                code=result.get("error_code") or "pages_connect_failed",
                message=result.get("message") or "فشل ربط الصفحات",
                details=result.get("details"),
                status_code=400,
            )

        pages_payload = result.get("pages") or []
        return ok_response(
            data=pages_payload,
            message=result.get("message"),
            legacy={"pages": pages_payload},
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="pages_connect_failed",
            message=str(exc),
            status_code=500,
        )
