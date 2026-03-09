# خدمة فيسبوك OAuth ونشر المنشورات — للنشر التلقائي تحت /autoposter
import requests
from urllib.parse import urlencode
from flask import current_app, g


def _get_facebook_config():
    """معرف التطبيق وسر التطبيق: من إعدادات الشركة أولاً، ثم من .env."""
    app_id = ""
    app_secret = ""
    if getattr(g, "tenant", None):
        try:
            from models.system_settings import SystemSettings
            s = SystemSettings.get_settings()
            if s:
                app_id = (getattr(s, "facebook_app_id", None) or "").strip()
                app_secret = (getattr(s, "facebook_app_secret", None) or "").strip()
        except Exception:
            pass
    if not app_id:
        app_id = (current_app.config.get("FACEBOOK_APP_ID") or "").strip()
    if not app_secret:
        app_secret = (current_app.config.get("FACEBOOK_APP_SECRET") or "").strip()
    return app_id, app_secret


def get_oauth_url(redirect_uri=None):
    """رابط تسجيل الدخول إلى فيسبوك لربط الصفحات. إذا مرّرت redirect_uri استُخدم كما هو."""
    app_id, _ = _get_facebook_config()
    if not redirect_uri:
        base = current_app.config.get("BASE_URL", "").rstrip("/")
        if not base:
            base = (current_app.config.get("PREFERRED_URL_SCHEME") or "https") + "://" + (current_app.config.get("SERVER_NAME") or "localhost")
        redirect_uri = f"{base}/autoposter/api/facebook/callback"
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement",
        "response_type": "code",
    }
    version = current_app.config.get("FACEBOOK_API_VERSION", "v21.0")
    return f"https://www.facebook.com/{version}/dialog/oauth?" + urlencode(params), redirect_uri


def exchange_code_for_user_token(code, redirect_uri):
    app_id, app_secret = _get_facebook_config()
    url = "https://graph.facebook.com/v21.0/oauth/access_token"
    r = requests.get(
        url,
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("access_token")


def get_long_lived_token(short_token):
    app_id, app_secret = _get_facebook_config()
    url = "https://graph.facebook.com/v21.0/oauth/access_token"
    r = requests.get(
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("access_token")


def get_pages_with_tokens(user_access_token):
    url = "https://graph.facebook.com/v21.0/me/accounts"
    r = requests.get(
        url,
        params={"access_token": user_access_token, "fields": "id,name,access_token"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def publish_post(page_access_token, message, photo_url=None, video_url=None, post_type="post", page_id=None):
    """
    ينشر حسب النوع:
    - post: منشور عادي (feed / صورة / فيديو)
    - story: ستوري (صورة أو فيديو)
    - reels: ريلز (فيديو)
    """
    version = "v21.0"
    base = f"https://graph.facebook.com/{version}"
    # للستوري والريلز نستخدم page_id في الرابط إن وُجد
    me_or_page = page_id if page_id else "me"

    if post_type == "story":
        if photo_url:
            url = f"{base}/{me_or_page}/photo_stories"
            payload = {"access_token": page_access_token, "url": photo_url}
        elif video_url:
            url = f"{base}/{me_or_page}/video_stories"
            payload = {"access_token": page_access_token, "file_url": video_url}
        else:
            raise Exception("الستوري يتطلب صورة أو فيديو")
    elif post_type == "reels":
        if not video_url:
            raise Exception("الريلز يتطلب فيديو")
        url = f"{base}/{me_or_page}/videos"
        payload = {"access_token": page_access_token, "file_url": video_url, "description": message or ""}
        # بعض التطبيقات تستخدم video_reels أو معامل إضافي؛ نستخدم نفس فيديو الصفحة
    else:
        # post (منشور عادي)
        if video_url:
            url = f"{base}/{me_or_page}/videos"
            payload = {"access_token": page_access_token, "file_url": video_url, "description": message or ""}
        elif photo_url:
            url = f"{base}/{me_or_page}/photos"
            payload = {"access_token": page_access_token, "url": photo_url, "message": message or ""}
        else:
            url = f"{base}/{me_or_page}/feed"
            payload = {"access_token": page_access_token, "message": message or ""}

    r = requests.post(url, data=payload, timeout=60 if video_url else 30)
    if r.status_code != 200:
        err = r.json() if r.text else {}
        raise Exception(err.get("error", {}).get("message", r.text))
    return r.json()
