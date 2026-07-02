#!/usr/bin/env python3
"""Merge curated help_pages and help_fields into translations/*.json."""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_help_content():
    path = os.path.join(ROOT, "data", "help_content.py")
    spec = importlib.util.spec_from_file_location("help_content", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def merge_lang(filepath: str, pages: dict, fields: dict) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_pages = data.get("help_pages") or {}
    for key, entry in pages.items():
        existing_pages[key] = entry
    data["help_pages"] = existing_pages

    existing_fields = data.get("help_fields") or {}
    for key, text in fields.items():
        existing_fields[key] = text
    data["help_fields"] = existing_fields

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def main() -> None:
    hc = _load_help_content()
    translations_dir = os.path.join(ROOT, "translations")

    merge_lang(
        os.path.join(translations_dir, "ar.json"),
        hc.HELP_PAGES_AR,
        hc.HELP_FIELDS_AR,
    )
    merge_lang(
        os.path.join(translations_dir, "en.json"),
        getattr(hc, "HELP_PAGES_EN", hc.HELP_PAGES_AR),
        {**hc.HELP_FIELDS_AR, **getattr(hc, "HELP_FIELDS_EN", {})},
    )
    for lang in ("tr", "ku"):
        merge_lang(
            os.path.join(translations_dir, f"{lang}.json"),
            hc.HELP_PAGES_AR,
            hc.HELP_FIELDS_AR,
        )
    print("Filled help_pages and help_fields in translations/")


if __name__ == "__main__":
    main()
