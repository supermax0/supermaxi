"""Central help content registry — loads from translations/*.json help_pages & help_fields."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache(maxsize=8)
def _load_lang_file(lang: str) -> dict[str, Any]:
    path = os.path.join(_ROOT, "translations", f"{lang}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _lang_data(lang: str) -> dict[str, Any]:
    data = _load_lang_file(lang)
    if data:
        return data
    return _load_lang_file("ar")


def get_help_fields(lang: str = "ar") -> dict[str, str]:
    fields = (_lang_data(lang).get("help_fields") or {})
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
