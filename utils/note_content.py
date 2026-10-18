"""Safe rich-text handling and local writing assistance for notebook entries."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


MAX_NOTE_HTML = 1_000_000
ALLOWED_TAGS = {
    "p", "div", "br", "strong", "b", "em", "i", "u", "s", "blockquote",
    "h1", "h2", "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody",
    "tr", "th", "td", "span", "font", "a", "img", "hr", "code", "pre", "mark",
}
VOID_TAGS = {"br", "hr", "img"}
ALLOWED_STYLES = {
    "color", "background-color", "font-family", "font-size", "text-align",
    "direction", "font-weight", "font-style", "text-decoration",
}


def _safe_style(value: str) -> str:
    declarations = []
    for raw in (value or "").split(";"):
        if ":" not in raw:
            continue
        key, val = raw.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key not in ALLOWED_STYLES or not val:
            continue
        if any(token in val.lower() for token in ("url(", "expression", "javascript:", "<", ">")):
            continue
        declarations.append(f"{key}:{val[:100]}")
    return ";".join(declarations)


class _NoteSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed", "svg", "form"}:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in ALLOWED_TAGS:
            return

        clean_attrs = []
        for key, value in attrs:
            key = key.lower()
            value = value or ""
            if key == "style":
                safe = _safe_style(value)
                if safe:
                    clean_attrs.append(("style", safe))
            elif key == "href" and tag == "a":
                if re.match(r"^(https?://|mailto:|tel:|/|#)", value, re.I):
                    clean_attrs.append(("href", value[:1000]))
                    clean_attrs.append(("rel", "noopener noreferrer"))
                    clean_attrs.append(("target", "_blank"))
            elif key == "src" and tag == "img":
                if re.match(r"^data:image/(png|jpeg|webp);base64,", value, re.I):
                    clean_attrs.append(("src", value[:MAX_NOTE_HTML]))
            elif key in {"colspan", "rowspan"} and tag in {"td", "th"}:
                clean_attrs.append((key, re.sub(r"\D", "", value)[:2] or "1"))
            elif key == "face" and tag == "font":
                face = re.sub(r"[^A-Za-z0-9\u0600-\u06ff _-]", "", value)[:60]
                if face:
                    clean_attrs.append(("face", face))
            elif key == "size" and tag == "font" and value in {"1", "2", "3", "4", "5", "6", "7"}:
                clean_attrs.append(("size", value))
            elif key == "color" and tag == "font":
                if re.fullmatch(r"(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})", value):
                    clean_attrs.append(("color", value))
            elif key == "align" and tag in {"p", "div", "h1", "h2", "h3", "h4"}:
                if value.lower() in {"left", "right", "center", "justify"}:
                    clean_attrs.append(("align", value.lower()))
            elif key == "dir" and tag in {"p", "div", "span", "h1", "h2", "h3", "h4"}:
                if value.lower() in {"rtl", "ltr", "auto"}:
                    clean_attrs.append(("dir", value.lower()))
            elif key == "data-checked" and tag == "span":
                clean_attrs.append(("data-checked", "true" if value.lower() == "true" else "false"))
            elif key == "data-state" and tag == "span":
                clean_attrs.append(("data-state", value if value in {"pending", "done", "cancelled"} else "pending"))
            elif key == "contenteditable" and tag == "span" and value.lower() == "false":
                clean_attrs.append(("contenteditable", "false"))
            elif key == "role" and tag == "span" and value.lower() == "checkbox":
                clean_attrs.append(("role", "checkbox"))
            elif key == "tabindex" and tag == "span" and value == "0":
                clean_attrs.append(("tabindex", "0"))
            elif key == "aria-checked" and tag == "span":
                clean_attrs.append(("aria-checked", "true" if value.lower() == "true" else "false"))
            elif key in {"data-chart", "data-chart-type"} and tag == "div":
                clean_attrs.append((key, value[:5000]))
            elif key == "class" and tag in {"div", "span", "table"}:
                allowed = " ".join(
                    item for item in value.split()
                    if item in {"note-chart", "note-callout", "note-table", "note-check", "note-priority"}
                )
                if allowed:
                    clean_attrs.append(("class", allowed))

        rendered = "".join(
            f' {key}="{html.escape(value, quote=True)}"' for key, value in clean_attrs
        )
        self.output.append(f"<{tag}{rendered}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed", "svg", "form"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked_depth:
            self.output.append(html.escape(data))


def sanitize_note_html(value: str) -> str:
    value = str(value or "")[:MAX_NOTE_HTML]
    parser = _NoteSanitizer()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def html_to_text(value: str) -> str:
    text = re.sub(r"<(?:br|/p|/div|/li|/h[1-6]|/tr)>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def organize_plain_text(text: str, mode: str = "organize") -> str:
    """Deterministically tidy Arabic/English notes without sending data externally."""
    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        return ""

    if mode == "tasks":
        items = []
        for line in lines:
            line = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line)
            checked = bool(re.match(r"^(?:تم|انجز|مكتمل|done)\b", line, re.I))
            items.append(f"<li>{'✅' if checked else '☐'} {html.escape(line)}</li>")
        return "<h2>قائمة المهام</h2><ul>" + "".join(items) + "</ul>"

    if mode == "summary":
        unique = list(dict.fromkeys(lines))
        return (
            "<h2>الخلاصة</h2><ul>"
            + "".join(f"<li>{html.escape(line)}</li>" for line in unique[:8])
            + "</ul>"
        )

    sections: list[tuple[str, list[str]]] = []
    current_title = "الأفكار الرئيسية"
    current_items: list[str] = []
    for index, line in enumerate(lines):
        is_heading = (
            line.endswith(":")
            or line.startswith("#")
            or (index == 0 and len(lines) > 1 and len(line) <= 45)
        )
        if is_heading and current_items:
            sections.append((current_title, current_items))
            current_items = []
        if is_heading:
            current_title = re.sub(r"^#+\s*|:\s*$", "", line) or current_title
        else:
            current_items.append(re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line))
    if current_items or not sections:
        sections.append((current_title, current_items or lines))

    rendered = []
    for title, items in sections:
        rendered.append(f"<h2>{html.escape(title)}</h2>")
        rendered.append("<ul>")
        rendered.extend(f"<li>{html.escape(item)}</li>" for item in items)
        rendered.append("</ul>")
    return "".join(rendered)
