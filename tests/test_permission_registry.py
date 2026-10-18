"""Every permission name the code checks must exist in the catalog — otherwise nobody but an admin can ever hold it.

Statically scans the server for ``employee_can / guard_permission / require / has_permission …("name")`` and
compares with the catalog the permissions screen offers."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKERS = {"employee_can", "check_permission", "guard_permission", "has_permission", "require", "can",
            "require_perm", "permission_required", "require_clinics", "require_permission", "requires_permission"}
NAME = re.compile(r"[a-z_]+([._][a-z_]+)*")
# Names that are dynamic/aliases rather than grantable rights.
NOT_RIGHTS: set[str] = set()


def referenced_permissions() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    files = [ROOT / "app.py"]
    for folder in ("routes", "modules", "utils", "services"):
        files += (ROOT / folder).rglob("*.py")
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name not in CHECKERS:
                continue
            for arg in node.args[:2]:
                values = [arg] if isinstance(arg, ast.Constant) else list(getattr(arg, "elts", []))
                for v in values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and NAME.fullmatch(v.value):
                        found.setdefault(v.value, set()).add(str(path.relative_to(ROOT)))
    return found


def test_every_checked_permission_is_in_the_catalog():
    from routes.permissions import DEFAULT_PERMISSIONS
    from utils.permission_checks import LEGACY_TO_RBAC

    known = {n for n, _ in DEFAULT_PERMISSIONS} | set(LEGACY_TO_RBAC) | set(LEGACY_TO_RBAC.values())
    orphans = {k: sorted(v)[:2] for k, v in referenced_permissions().items() if k not in known and k not in NOT_RIGHTS}
    assert orphans == {}, f"permissions checked in code but missing from DEFAULT_PERMISSIONS: {orphans}"


def test_every_default_permission_has_a_label_and_a_display_group():
    from routes.permissions import DEFAULT_PERMISSIONS, PERMISSION_GROUPS

    grouped = {n for _, _, names in PERMISSION_GROUPS for n in names}
    names = [n for n, _ in DEFAULT_PERMISSIONS]
    assert len(names) == len(set(names)), "duplicate permission names"
    assert all(label.strip() for _, label in DEFAULT_PERMISSIONS)
    ungrouped = sorted(set(names) - grouped - {"view_all_branches"})
    # permissions of niche modules may fall into «أخرى», but the new platform ones must be grouped
    assert not [n for n in ungrouped if n.startswith(("finance.", "hr.", "inventory.audit.", "mobile_app."))], ungrouped


def test_every_permission_the_desktop_session_reports_is_grantable():
    from modules.desktop_api.routes import DESKTOP_PERMISSIONS
    from routes.permissions import DEFAULT_PERMISSIONS
    from utils.permission_checks import LEGACY_TO_RBAC

    known = {n for n, _ in DEFAULT_PERMISSIONS} | set(LEGACY_TO_RBAC) | set(LEGACY_TO_RBAC.values())
    assert sorted(set(DESKTOP_PERMISSIONS) - known - {"view_all_branches", "wholesale_warehouses", "manage_permissions"}) == []
