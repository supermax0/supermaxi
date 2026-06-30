from __future__ import annotations


def should_use_dev_ui() -> bool:
    return False


def storefront_template(name: str) -> str:
    return f"storefront/{name}"
