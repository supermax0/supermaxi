# -*- coding: utf-8 -*-
"""Repair broken Jinja in templates/invoices/*.html (CSS variables + custom_css)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "templates" / "invoices"

BROKEN_CUSTOM = """            {
            % if template_styles and template_styles.custom_css %
        }

            {
                {
                template_styles.custom_css | safe
            }
        }

            {
            % endif %
        }"""

FIXED_CUSTOM = """{% if template_styles and template_styles.custom_css %}
{{ template_styles.custom_css | safe }}
{% endif %}"""

PRI_RE = re.compile(
    r"--primary-color:\s*\{\s*\{\s*template_styles\.primary if template_styles and template_styles\.primary else '([^']+)'\s*\}\s*\}\s*;",
    re.DOTALL,
)
SEC_RE = re.compile(
    r"--secondary-color:\s*\{\s*\{\s*template_styles\.secondary if template_styles and template_styles\.secondary else '([^']+)'\s*\}\s*\}\s*;",
    re.DOTALL,
)


def fix_file(text: str) -> str:
    def rp(m):
        c = m.group(1)
        return (
            f"--primary-color: {{{{ template_styles.primary if template_styles and template_styles.primary else '{c}' }}}};"
        )

    def rs(m):
        c = m.group(1)
        return (
            f"--secondary-color: {{{{ template_styles.secondary if template_styles and template_styles.secondary else '{c}' }}}};"
        )

    text, n1 = PRI_RE.subn(rp, text, count=1)
    if n1 != 1:
        raise ValueError("primary block not replaced exactly once")
    if SEC_RE.search(text):
        text, n2 = SEC_RE.subn(rs, text, count=1)
        if n2 != 1:
            raise ValueError("secondary block not replaced exactly once")
    if BROKEN_CUSTOM in text:
        text = text.replace(BROKEN_CUSTOM, FIXED_CUSTOM, 1)
    return text


def main():
    for path in sorted(ROOT.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        if "{{ template_styles.primary if template_styles" in raw and "{% if template_styles and template_styles.custom_css %}" in raw:
            print("skip", path.name)
            continue
        new = fix_file(raw)
        path.write_text(new, encoding="utf-8")
        print("patched", path.name)


if __name__ == "__main__":
    main()
