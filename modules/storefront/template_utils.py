from __future__ import annotations

from flask import current_app, request
from jinja2 import TemplateNotFound


def should_use_dev_ui() -> bool:
    return request.args.get("dev") == "1"


def storefront_template(name: str) -> str:
    if should_use_dev_ui():
        dev = f"storefront_dev/{name}"
        try:
            current_app.jinja_env.get_template(dev)
            return dev
        except TemplateNotFound:
            pass
    return f"storefront/{name}"
