"""Background jobs for clinic reminders across tenants."""
from __future__ import annotations

import logging

from flask import Flask, g

_log = logging.getLogger(__name__)


def process_clinic_jobs_for_current_tenant() -> dict:
    from extensions import db
    from modules.clinics.schema import ensure_clinics_schema
    from modules.clinics.service import get_or_create_settings
    from modules.clinics.service_comms import process_pending_reminders, schedule_appointment_reminders
    from models.tenant import Tenant

    ensure_clinics_schema()
    tenant = Tenant.query.first()
    tenant_id = int(tenant.id) if tenant else 1
    settings = get_or_create_settings(tenant_id)
    scheduled = schedule_appointment_reminders(tenant_id)
    processed = process_pending_reminders(tenant_id) if settings.whatsapp_notifications_enabled else {"processed": 0, "sent": 0, "failed": 0, "skipped": True}
    db.session.commit()
    return {"tenant_id": tenant_id, "scheduled": scheduled, **processed}


def run_clinic_jobs_all_tenants(app: Flask) -> dict:
    from models.core.tenant import Tenant as CoreTenant

    summary = {"tenants": 0, "ok": 0, "errors": 0}
    with app.app_context():
        try:
            tenants = CoreTenant.query.filter_by(is_active=True, business_type="clinics").all()
        except Exception:
            try:
                tenants = CoreTenant.query.filter_by(is_active=True).all()
            except Exception:
                tenants = []
        for t in tenants:
            slug = getattr(t, "slug", None)
            if not slug:
                continue
            summary["tenants"] += 1
            g.tenant = slug
            try:
                process_clinic_jobs_for_current_tenant()
                summary["ok"] += 1
            except Exception:
                summary["errors"] += 1
                _log.exception("clinic jobs failed for %s", slug)
                try:
                    from extensions import db

                    db.session.rollback()
                except Exception:
                    pass
            finally:
                g.tenant = None
    return summary


def start_clinics_scheduler(app: Flask) -> None:
    import os
    import sys

    if os.environ.get("DISABLE_CLINICS_SCHEDULER") == "1":
        return
    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        # Prefer explicit worker/cron in production; keep manual API available.
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        def _tick():
            try:
                run_clinic_jobs_all_tenants(app)
            except Exception:
                _log.exception("clinics scheduler tick failed")

        scheduler = BackgroundScheduler()
        scheduler.add_job(_tick, IntervalTrigger(minutes=5), id="clinics_reminders")
        scheduler.start()
        app.extensions["clinics_scheduler"] = scheduler
    except Exception:
        _log.exception("failed to start clinics scheduler")
