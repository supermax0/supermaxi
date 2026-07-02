#!/usr/bin/env python3
"""Scan route files and merge help_pages skeleton into translations/*.json."""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_DECORATOR = re.compile(
    r"@(\w+)(?:_bp)?\.route\(\s*['\"]([^'\"]+)['\"]"
)
BLUEPRINT_DEF = re.compile(
    r"(\w+)_bp\s*=\s*Blueprint\(\s*['\"](\w+)['\"]"
)


def _endpoint_title(endpoint: str) -> str:
    parts = endpoint.replace("_", " ").split(".")
    name = parts[-1] if parts else endpoint
    mapping = {
        "index": "الصفحة الرئيسية",
        "list": "القائمة",
        "create": "إنشاء",
        "edit": "تعديل",
        "view": "عرض",
        "dashboard": "لوحة التحكم",
        "settings": "الإعدادات",
        "reports": "التقارير",
    }
    return mapping.get(name, name)


def collect_endpoints_from_routes() -> dict[str, dict]:
    routes_dir = os.path.join(ROOT, "routes")
    pages: dict[str, dict] = {}

    for filename in os.listdir(routes_dir):
        if not filename.endswith(".py"):
            continue
        filepath = os.path.join(routes_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        bp_name = filename.replace(".py", "")
        bp_match = BLUEPRINT_DEF.search(content)
        if bp_match:
            bp_name = bp_match.group(2)

        for match in ROUTE_DECORATOR.finditer(content):
            var_name, path = match.groups()
            if var_name not in (f"{bp_name}_bp", "bp", "app"):
                continue
            func_match = re.search(
                rf"@(?:{re.escape(var_name)})\.route\(\s*['\"]{re.escape(path)}['\"][^\)]*\)\s*\n\s*def\s+(\w+)",
                content,
            )
            func_name = func_match.group(1) if func_match else "index"
            endpoint = f"{bp_name}.{func_name}"
            title = _endpoint_title(endpoint)
            body = f"صفحة {title}. استخدم الأدوات والفلاتر المتاحة لإدارة بياناتك."
            pages[endpoint] = {"title": title, "body": body}
            path_key = path.strip("/").replace("/", ".") or "index"
            if path_key and path_key != endpoint:
                pages[path_key] = {"title": title, "body": body}

    return pages


def merge_into_lang_file(filepath: str, pages: dict[str, dict]) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_pages = data.get("help_pages") or {}
    for key, entry in pages.items():
        if key not in existing_pages:
            existing_pages[key] = entry

    data["help_pages"] = existing_pages
    if "help_fields" not in data:
        data["help_fields"] = {}

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def main() -> None:
    pages = collect_endpoints_from_routes()
    translations_dir = os.path.join(ROOT, "translations")
    for filename in os.listdir(translations_dir):
        if not filename.endswith(".json"):
            continue
        merge_into_lang_file(os.path.join(translations_dir, filename), pages)
    print(f"Merged {len(pages)} help_pages keys into translations/")


if __name__ == "__main__":
    main()
