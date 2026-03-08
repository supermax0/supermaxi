# خدمة فيسبوك OAuth ونشر المنشورات — للنشر التلقائي تحت /autoposter
import requests
from urllib.parse import urlencode
from flask import current_app


def get_oauth_url(redirect_uri=None):
    """رابط تسجيل الدخول إلى فيسبوك لربط الصفحات. إذا مرّرت redirect_uri استُخدم كما هو."""
    if not redirect_uri:
        base = current_app.config.get("BASE_URL", "").rstrip("/")
        if not base:
            base = (current_app.config.get("PREFERRED_URL_SCHEME") or "https") + "://" + (current_app.config.get("SERVER_NAME") or "localhost")
        redirect_uri = f"{base}/autoposter/api/facebook/callback"
    params = {
        "client_id": current_app.config.get("FACEBOOK_APP_ID") or "",
        "redirect_uri": redirect_uri,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement",
        "response_type": "code",
    }
    version = current_app.config.get("FACEBOOK_API_VERSION", "v21.0")
    return f"https://www.facebook.com/{version}/dialog/oauth?" + urlencode(params), redirect_uri


def exchange_code_for_user_token(code, redirect_uri):
    url = "https://graph.facebook.com/v21.0/oauth/access_token"
    r = requests.get(
        url,
        params={
            "client_id": current_app.config["FACEBOOK_APP_ID"],
            "client_secret": current_app.config["FACEBOOK_APP_SECRET"],
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("access_token")


def get_long_lived_token(short_token):
    url = "https://graph.facebook.com/v21.0/oauth/access_token"
    r = requests.get(
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": current_app.config["FACEBOOK_APP_ID"],
            "client_secret": current_app.config["FACEBOOK_APP_SECRET"],
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


def publish_post(page_access_token, message, photo_url=None):
    if photo_url:
        url = "https://graph.facebook.com/v21.0/me/photos"
        payload = {"access_token": page_access_token, "url": photo_url, "message": message or ""}
    else:
        url = "https://graph.facebook.com/v21.0/me/feed"
        payload = {"access_token": page_access_token, "message": message or ""}
    r = requests.post(url, data=payload, timeout=30)
    if r.status_code != 200:
        err = r.json() if r.text else {}
        raise Exception(err.get("error", {}).get("message", r.text))
    return r.json()
