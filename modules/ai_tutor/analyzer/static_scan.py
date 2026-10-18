"""Static analyzer: discovers what Finora Clinics really contains by reading its source files.

Never imports the app, never touches a database and never edits the knowledge registry.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = ROOT / "templates" / "clinics"
STATIC_DIR = ROOT / "static" / "clinics"
ROUTES_FILE = ROOT / "modules" / "clinics" / "routes.py"
GUARDS_FILE = ROOT / "modules" / "clinics" / "guards.py"

KINDS = ("page", "section", "action", "field")
ATTR_RE = re.compile(r'data-finora-(page|section|action|field)\s*=\s*"([^"]+)"')
# JS option that sets data-finora-action at runtime: `finoraAction: cond ? "a" : "b"` or `finoraAction: `${x}.save``
OPTION_RE = re.compile(r"finoraAction:\s*(.+)")
QUOTED_RE = re.compile(r'"([^"]+)"|`([^`]+)`')
PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}|\{\{[^}]*\}\}|\{%[^%]*%\}")
INNER_TEXT_RE = re.compile(r"^(.{0,400}?)</(?:a|button|label|h\d|summary)>", re.S)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$", re.I)

# Values of known template placeholders (the same expansions the UI sources actually render).
EXPANSIONS = {
    "${fp}": ["doctor", "employee", "staff"], "${staffType}": ["doctor", "employee"],
    # appointments.js openAction(status): the card to open depends on the appointment stage
    # staff.js permissionsHtml(): one fieldset per permission group of CLINIC_PERMISSION_CATALOG
    "${group.key}": ["daily", "clinical", "finance", "communication", "admin"],
    "${openAction(a.status)}": ["appointment.open", "appointment.open.scheduled", "appointment.open.arrived", "appointment.open.waiting"],
    # finance-shared.js headerHtml(): a header action button may declare its own data-finora-action
    "${ctx.esc(a.finoraAction)}": ["payment.record"],
}

# The source file (or id prefix) that owns an element decides its page when no runtime scan says otherwise.
FILE_PAGE = {"staff.js": "staff"}
PREFIX_PAGE = {"appointment": "appointments", "schedule": "schedules", "doctor": "staff", "employee": "staff", "staff": "staff", "specialty": "specialties", "nav": "global", "modal": "global"}

CATEGORY_CHROME_PREFIXES = ("nav.menu.", "modal.")
CATEGORY_SUBMIT_SUFFIXES = (".save", ".save.edit", ".confirm")


def category_of(kind: str, ident: str) -> str:
    """feature = user-facing capability; navigation = sidebar link; chrome = generic UI plumbing; submit = form save buttons."""
    if kind != "action":
        return "structure"
    if (ident.startswith(CATEGORY_CHROME_PREFIXES) or ident.endswith("_pick")
            or ident.endswith((".open", ".select", ".apply", ".drawer", ".toggle")) or ".open." in ident or ".tab." in ident):
        return "chrome"  # plumbing: opening a record / an alternate entry point to a lesson, not a feature of its own
    if ident.endswith(CATEGORY_SUBMIT_SUFFIXES):
        return "submit"
    if ident.startswith("nav."):
        return "navigation"
    return "feature"


def infer_page(ident: str, file: str) -> str | None:
    name = Path(file).name
    if ident.startswith(("nav.", "modal.")):
        return PREFIX_PAGE.get(ident.split(".")[0])
    if name in FILE_PAGE:
        return FILE_PAGE[name]
    page = PREFIX_PAGE.get(ident.split(".")[0])
    if page:
        return page
    # A page script named after its page (patients.js -> patients) owns the elements it renders.
    stem = Path(file).stem
    return stem if stem in page_config() else None


@dataclass
class Item:
    kind: str
    id: str
    files: set[str] = field(default_factory=set)
    lines: list[str] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)
    dynamic: bool = False  # produced from JS options / expanded placeholders


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _label_after(text: str, tag_start: int) -> str | None:
    """Best-effort visible label of the tag that carries the attribute (literal text only)."""
    tag_end = text.find(">", tag_start)
    if tag_end < 0:
        return None
    match = INNER_TEXT_RE.match(text[tag_end + 1: tag_end + 1 + 420])
    if not match:
        return None
    label = re.sub(r"<[^>]*>", " ", match.group(1))
    label = re.sub(r"\s+", " ", label).strip()
    if not label or PLACEHOLDER_RE.search(label) or len(label) > 60 or not re.search(r"[؀-ۿ]|[A-Za-z]{2}", label):
        return None
    return label


def _expand(value: str, page_ids: list[str]) -> list[str] | None:
    """Resolve template placeholders; None = cannot be resolved statically."""
    if "{{" in value and "clinics_page" in value:
        return list(page_ids)
    out = [value]
    for token, values in EXPANSIONS.items():
        if token in value:
            out = [o.replace(token, v) for o in out for v in values]
    return None if any(PLACEHOLDER_RE.search(o) for o in out) else out


def scan_text(text: str, file: str, page_ids: list[str], items: dict, unresolved: list) -> None:
    def add(kind: str, ident: str, index: int, label: str | None = None, dynamic: bool = False) -> None:
        if not ID_RE.match(ident):
            unresolved.append({"file": file, "line": _line_of(text, index), "value": ident, "reason": "unstable-id"})
            return
        item = items.setdefault((kind, ident), Item(kind, ident))
        item.files.add(file)
        item.lines.append(f"{file}:{_line_of(text, index)}")
        item.dynamic = item.dynamic or dynamic
        if label:
            item.labels.add(label)

    for match in ATTR_RE.finditer(text):
        kind, raw = match.group(1), match.group(2)
        values = _expand(raw, page_ids)
        if values is None:
            unresolved.append({"file": file, "line": _line_of(text, match.start()), "value": raw, "reason": "unresolved-placeholder"})
            continue
        label = _label_after(text, match.start()) if kind == "action" else None
        for value in values:
            add(kind, value, match.start(), label, dynamic=value != raw)
    for match in OPTION_RE.finditer(text):
        for quoted in QUOTED_RE.finditer(match.group(1)):
            raw = quoted.group(1) or quoted.group(2)
            values = _expand(raw, page_ids)
            if values is None:
                unresolved.append({"file": file, "line": _line_of(text, match.start()), "value": raw, "reason": "unresolved-placeholder"})
                continue
            for value in values:
                add("action", value, match.start(), dynamic=True)


# --------------------------------------------------------------- python sources

_LITERAL_CACHE: dict = {}


def _literal_assign(path: Path, name: str):
    """Module-level literal assignment, parsed from source (cached per file version: the routes file is large)."""
    stat = path.stat()
    key = (str(path), name, stat.st_mtime_ns, stat.st_size)
    if key in _LITERAL_CACHE:
        return _LITERAL_CACHE[key]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            _LITERAL_CACHE[key] = ast.literal_eval(node.value)
            return _LITERAL_CACHE[key]
    raise LookupError(f"{name} not found in {path.name}")


def page_config() -> dict[str, tuple[str, str]]:
    """{page_id: (title_ar, required_permission)} straight from the routes source."""
    return {k: tuple(v) for k, v in _literal_assign(ROUTES_FILE, "PAGE_CONFIG").items()}


def known_permissions() -> tuple[str, ...]:
    return tuple(_literal_assign(GUARDS_FILE, "CLINICS_PERMISSIONS"))


ROUTE_RE = re.compile(r'@clinics_bp\.(route|get|post|put|patch|delete)\(\s*"([^"]*)"(?:\s*,\s*methods=\[([^\]]*)\])?')
PERMISSION_RE = re.compile(r'@require_clinics\(\s*(None|"[^"]*")?')


def backend_endpoints() -> list[dict]:
    """[{rule, methods, permission}] for every clinics_bp route, with the permission its decorator requires."""
    lines = ROUTES_FILE.read_text(encoding="utf-8").splitlines()
    endpoints = []
    for index, line in enumerate(lines):
        match = ROUTE_RE.match(line.strip())
        if not match:
            continue
        verb, rule, methods = match.groups()
        verbs = [m.strip(" \"'").upper() for m in methods.split(",")] if methods else [("GET" if verb == "route" else verb.upper())]
        permission = None
        for follower in lines[index + 1: index + 6]:
            decorated = PERMISSION_RE.match(follower.strip())
            if decorated:
                value = decorated.group(1)
                permission = value.strip('"') if value and value != "None" else None
                break
        endpoints.append({"rule": "/clinics" + (rule if rule != "/" else "/"), "methods": verbs, "permission": permission})
    return endpoints


def has_page_route() -> bool:
    text = ROUTES_FILE.read_text(encoding="utf-8")
    return '@clinics_bp.route("/<page>")' in text and '@clinics_bp.route("/")' in text


def rule_matches(rule: str, method: str, pattern: str) -> bool:
    """Does the tutorial's `match.url` regex fit a real backend rule (placeholders replaced by sample values)?"""
    sample = re.sub(r"<int:[^>]+>", "1", rule)
    sample = re.sub(r"<[^>]+>", "x", sample)
    return bool(re.search(pattern, sample))


# ---------------------------------------------------------------------- scan

def source_files() -> list[Path]:
    files = sorted(TEMPLATE_DIR.glob("*.html")) + sorted(STATIC_DIR.glob("*.js"))
    return [f for f in files if not f.name.endswith(".min.js")]


def fingerprint() -> str:
    """Cheap change detector: names, sizes and mtimes of every scanned source (a stale snapshot is detectable)."""
    digest = hashlib.sha1()
    for path in [*source_files(), ROUTES_FILE, GUARDS_FILE]:
        stat = path.stat()
        digest.update(f"{path.relative_to(ROOT)}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    from modules.ai_tutor import registry as tutorials
    for path in sorted(tutorials.TUTORIALS_DIR.glob("*.json")):
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    knowledge = ROOT / "modules" / "ai_tutor" / "knowledge"
    for path in sorted(knowledge.glob("*.json")):
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


def scan_sources() -> dict:
    """Run the static analyzer. Returns plain data (no objects) so it can be stored in a snapshot."""
    pages = page_config()
    items: dict[tuple[str, str], Item] = {}
    unresolved: list[dict] = []
    for path in source_files():
        scan_text(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)).replace("\\", "/"), list(pages), items, unresolved)
    result_items = []
    for (kind, ident), item in sorted(items.items()):
        files = sorted(item.files)
        result_items.append({
            "kind": kind, "id": ident, "files": files, "lines": item.lines[:6], "labels": sorted(item.labels),
            "dynamic": item.dynamic, "category": category_of(kind, ident),
            "page": None if kind == "page" else infer_page(ident, files[0]),
        })
    return {"items": result_items, "unresolved": unresolved, "pages": pages,
            "page_route_present": has_page_route(), "endpoints": backend_endpoints(),
            "permissions": list(known_permissions()), "files_scanned": len(source_files())}
