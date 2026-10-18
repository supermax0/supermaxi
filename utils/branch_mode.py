"""Per-company operating mode for branch isolation."""
from __future__ import annotations

import json

from flask import g, has_app_context
from sqlalchemy import inspect, text

from extensions import db


INDEPENDENT_BRANCHES_FLAG = "independent_branches_enabled"
BRANCH_SCOPE_MIGRATION_FLAG = "branch_scope_v3_done"
LEGACY_SHARED_MODE_FLAG = "legacy_shared_mode_enabled"


def mode_enabled_from_flags(flags: dict | None) -> bool:
    """Resolve the safe company mode from persisted flags."""
    values = flags if isinstance(flags, dict) else {}
    # Explicit compatibility mode keeps all migrated rows intact while the
    # company operates with one shared view. It is intentionally separate
    # from the migration marker so no historical branch ownership is erased.
    if values.get(LEGACY_SHARED_MODE_FLAG, False):
        return False
    return bool(
        values.get(BRANCH_SCOPE_MIGRATION_FLAG, False)
        or values.get(INDEPENDENT_BRANCHES_FLAG, True)
    )


def _read_flags() -> dict:
    """Read only ui_flags, avoiding unrelated legacy settings columns."""
    try:
        connection = db.session.connection()
        if not inspect(connection).has_table("system_settings"):
            return {}
        raw = db.session.execute(
            text("SELECT ui_flags FROM system_settings ORDER BY id LIMIT 1")
        ).scalar()
        flags = json.loads(raw or "{}")
        return flags if isinstance(flags, dict) else {}
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {}


def independent_branches_enabled() -> bool:
    """Return the tenant mode; independent branches are on by default."""
    if has_app_context():
        cached = getattr(g, "independent_branches_enabled", None)
        if cached is not None:
            return bool(cached)
    # A completed localization cannot safely be treated as the legacy shared
    # catalogue again. Reverting requires restoring the pre-migration backup.
    enabled = mode_enabled_from_flags(_read_flags())
    if has_app_context():
        g.independent_branches_enabled = enabled
    return enabled


def independent_branch_migration_completed() -> bool:
    return bool(_read_flags().get(BRANCH_SCOPE_MIGRATION_FLAG, False))


def clear_branch_mode_cache() -> None:
    if has_app_context():
        g.pop("independent_branches_enabled", None)
