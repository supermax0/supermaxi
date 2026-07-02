"""Central help content registry — loads from translations/*.json help_pages & help_fields."""
from __future__ import annotations

import json
from typing import Any


def _lang_data(lang: str) -> dict:
    try:
        from app import app_translations
    except ImportError:
        return {}
    return app_translations.get(lang) or app_translations.get("ar") or {}


def get_help_fields(lang: str = "ar") -> dict[str, str]:
    data = _lang_data(lang)
    fields = data.get("help_fields") or {}
    return {k: v for k, v in fields.items() if isinstance(v, str)}


def get_page_help(endpoint: str | None, path: str, lang: str = "ar") -> dict[str, str] | None:
    pages = (_lang_data(lang).get("help_pages") or {})
    if not pages:
        return None

    if endpoint and endpoint in pages:
        entry = pages[endpoint]
        if isinstance(entry, dict) and entry.get("body"):
            return {"key": endpoint, "title": entry.get("title", ""), "body": entry["body"]}
        if isinstance(entry, str):
            return {"key": endpoint, "title": "", "body": entry}

    path_key = (path or "").strip("/").replace("/", ".") or "index"
    if path_key in pages:
        entry = pages[path_key]
        if isinstance(entry, dict) and entry.get("body"):
            return {"key": path_key, "title": entry.get("title", ""), "body": entry["body"]}
        if isinstance(entry, str):
            return {"key": path_key, "title": "", "body": entry}

    return None


def get_field_help(key: str, lang: str = "ar") -> str:
    if not key:
        return ""
    return get_help_fields(lang).get(key, "")


def help_fields_json(lang: str = "ar") -> str:
    return json.dumps(get_help_fields(lang), ensure_ascii=False)
