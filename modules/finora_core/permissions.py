"""Role → permission map for desktop operators (spec §38)."""
from __future__ import annotations

ALL_PERMISSIONS = frozenset(
    {
        "conversations.view",
        "messages.send",
        "ai.takeover",
        "notes.write",
        "tenants.create",
        "approvals.decide",
        "audit.view",
        "settings.manage",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "super_admin": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS - {"settings.manage"},
    "sales": frozenset({"conversations.view", "messages.send", "ai.takeover", "notes.write", "tenants.create"}),
    "support": frozenset({"conversations.view", "messages.send", "ai.takeover", "notes.write"}),
    "read_only": frozenset({"conversations.view", "audit.view"}),
}

DEFAULT_ROLE = "super_admin"


def permissions_for(role: str) -> frozenset[str]:
    """Unknown roles get nothing (fail closed)."""
    return ROLE_PERMISSIONS.get(role, frozenset())
