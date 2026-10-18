from __future__ import annotations

from pathlib import Path

from flask import g, has_request_context, request, session

# Smart Commerce V2 design: opt-in per company (ui_flags["storefront_v2"]) so existing shops keep their look.
# The owner can preview it without enabling it: ?v2=1 turns the preview on for this browser, ?v2=0 turns it off.
V2_FLAG = "storefront_v2"
V2_PREVIEW_KEY = "sf_v2_preview"
_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def should_use_dev_ui() -> bool:
    return False


def v2_enabled() -> bool:
    if not has_request_context():
        return False
    cached = getattr(g, "_sf_v2", None)
    if cached is not None:
        return cached
    g._sf_v2 = _decide()
    return g._sf_v2


def _decide() -> bool:
    choice = request.args.get("v2")
    if choice in ("0", "1"):
        session[V2_PREVIEW_KEY] = choice == "1"
    if session.get(V2_PREVIEW_KEY) is not None:
        return bool(session.get(V2_PREVIEW_KEY))
    try:
        from modules.storefront.services.settings_service import StorefrontSettingsService

        return bool(StorefrontSettingsService().ui_flags().get(V2_FLAG))
    except Exception:
        return False


def storefront_template(name: str) -> str:
    if v2_enabled() and (_TEMPLATES / "storefront_v2" / name).is_file():
        return f"storefront_v2/{name}"
    return f"storefront/{name}"


def storefront_base() -> str:
    """The page shell pages extend: the V2 shell when V2 is on, else the existing one."""
    return "storefront_v2/base.html" if v2_enabled() else "storefront/base.html"
