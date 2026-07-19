#!/usr/bin/env python3
"""Poll Meta conversations when webhook delivery is unavailable."""

import json
import os
import sys
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path


# Importing the Flask app must not start any of the in-process schedulers.
os.environ.setdefault("SERVER_SOFTWARE", "gunicorn/finora-meta-sync")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import g  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models.core.tenant import Tenant as CoreTenant  # noqa: E402
from modules.ai_sales.routes import _sync_meta_channels  # noqa: E402
from modules.ai_sales.schema import ensure_ai_sales_schema  # noqa: E402


def sync_once(*, ai_only: bool) -> int:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenants": [],
    }
    with app.app_context():
        g.tenant = None
        try:
            tenants = CoreTenant.query.filter_by(is_active=True).all()
        except Exception as exc:
            app.logger.exception("Finora Sales AI could not list active tenants")
            report["fatal_error"] = str(exc)
            print(json.dumps(report, ensure_ascii=False, default=str))
            return 1
        finally:
            db.session.remove()

        for tenant in tenants:
            slug = str(getattr(tenant, "slug", "") or "").strip()
            if not slug:
                continue
            g.tenant = slug
            try:
                ensure_ai_sales_schema()
                result = _sync_meta_channels(ai_only=ai_only, asynchronous=False)
                report["tenants"].append({"tenant": slug, **result})
            except Exception as exc:
                db.session.rollback()
                app.logger.exception("Finora Sales AI Meta sync failed tenant=%s", slug)
                report["tenants"].append({"tenant": slug, "fatal_error": str(exc)})
            finally:
                db.session.remove()
                g.tenant = None

    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=max_interval, default=10)
    parser.add_argument("--full-interval", type=max_interval, default=60)
    args = parser.parse_args()

    if not args.loop:
        return sync_once(ai_only=False)

    next_full_sync = 0.0
    while True:
        started_at = time.monotonic()
        full_sync = started_at >= next_full_sync
        sync_once(ai_only=not full_sync)
        if full_sync:
            next_full_sync = time.monotonic() + args.full_interval
        elapsed = time.monotonic() - started_at
        time.sleep(max(1.0, args.interval - elapsed))


def max_interval(value: str) -> int:
    return max(5, int(value))


if __name__ == "__main__":
    raise SystemExit(main())
