"""Platform-wide branding (logo, app name) stored in Core DB GlobalSetting."""

import os
from datetime import datetime

from werkzeug.utils import secure_filename

DEFAULT_LOGO_PATH = "/static/finora-logo.png"
DEFAULT_APP_NAME = "Finora"
LOGO_SETTING_KEY = "APP_LOGO_PATH"
APP_NAME_SETTING_KEY = "APP_NAME"
UPLOAD_FOLDER = "static/uploads/platform"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}


def _with_core_db(fn):
    from flask import g
    from extensions import db

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        db.session.rollback()
        return fn()
    except Exception:
        db.session.rollback()
        raise
    finally:
        g.tenant = old_tenant


def get_platform_logo_url(*, cache_bust=True):
    def _read():
        from models.core.global_setting import GlobalSetting

        row = GlobalSetting.query.filter_by(key=LOGO_SETTING_KEY).first()
        path = (row.value if row and row.value else "").strip()
        path = path or DEFAULT_LOGO_PATH
        version = ""
        if cache_bust and path != DEFAULT_LOGO_PATH and row and row.updated_at:
            version = str(int(row.updated_at.timestamp()))
        return path, version

    try:
        path, version = _with_core_db(_read)
    except Exception:
        return DEFAULT_LOGO_PATH

    if version:
        return f"{path}?v={version}"
    return path


def get_platform_logo_path():
    """Raw stored logo path without cache-busting query."""
    url = get_platform_logo_url(cache_bust=False)
    return url.split("?", 1)[0]


def get_platform_app_name():
    def _read():
        from models.core.global_setting import GlobalSetting

        name = (GlobalSetting.get_setting(APP_NAME_SETTING_KEY, DEFAULT_APP_NAME) or "").strip()
        return name or DEFAULT_APP_NAME

    try:
        return _with_core_db(_read)
    except Exception:
        return DEFAULT_APP_NAME


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_platform_logo(file, app_root):
    from models.core.global_setting import GlobalSetting

    if not file or not file.filename:
        raise ValueError("لم يتم اختيار ملف")

    if not allowed_file(file.filename):
        raise ValueError("نوع الملف غير مدعوم")

    upload_dir = os.path.join(app_root, UPLOAD_FOLDER)
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"platform_logo_{timestamp}_{filename}"
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    logo_path = f"/{UPLOAD_FOLDER}/{filename}"

    def _save():
        old_path = (GlobalSetting.get_setting(LOGO_SETTING_KEY, "") or "").strip()
        GlobalSetting.set_setting(LOGO_SETTING_KEY, logo_path, "شعار المنصة (لوحة التحكم والصفحات العامة)")
        _delete_old_logo_file(app_root, old_path, logo_path)
        return logo_path

    return _with_core_db(_save)


def remove_platform_logo(app_root):
    from models.core.global_setting import GlobalSetting

    def _remove():
        old_path = (GlobalSetting.get_setting(LOGO_SETTING_KEY, "") or "").strip()
        GlobalSetting.set_setting(LOGO_SETTING_KEY, "", "شعار المنصة (لوحة التحكم والصفحات العامة)")
        _delete_old_logo_file(app_root, old_path, "")
        return True

    return _with_core_db(_remove)


def _delete_old_logo_file(app_root, old_path, keep_path=""):
    if not old_path or old_path == keep_path or not old_path.startswith("/static/uploads/platform/"):
        return
    abs_path = os.path.join(app_root, old_path.lstrip("/"))
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass
