"""Shared helpers for Leads CRM services."""


def actor_superadmin_id() -> int | None:
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return None
        return session.get("superadmin_id")
    except Exception:
        return None
