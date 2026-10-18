import re
from html import escape

from markupsafe import Markup


_BULLET_RE = re.compile(r"^\s*(?:[-•‣◦▪]|(?<!\*)\*(?!\*)|(?:\d+|[٠-٩]+|[۰-۹]+)[\.\)-])\s+(.+?)\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_SPLIT_RE = re.compile(r"\s+(?=(?:[-•‣◦▪]\s+|(?<!\*)\*(?!\*)\s+|(?:\d+|[٠-٩]+|[۰-۹]+)[\.\)-]\s+))")


def _prepare_lines(value):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    prepared = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            prepared.append("")
            continue

        split_line = _INLINE_SPLIT_RE.sub("\n", line)
        prepared.extend(part.strip() for part in split_line.split("\n"))
    return prepared


def _format_inline(text):
    escaped = escape(str(text or "").strip())
    return _INLINE_BOLD_RE.sub(lambda match: f"<strong>{match.group(1)}</strong>", escaped)


def format_invoice_text(value):
    lines = _prepare_lines(value)
    if not lines:
        return Markup("")

    html_parts = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    for line in lines:
        if not line:
            close_list()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            close_list()
            html_parts.append(f"<h4>{_format_inline(heading.group(1))}</h4>")
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_format_inline(bullet.group(1))}</li>")
            continue

        close_list()
        html_parts.append(f"<p>{_format_inline(line)}</p>")

    close_list()
    return Markup("".join(html_parts))
