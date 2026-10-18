"""Helper for load_storefront.py: seed a throw-away store and serve the app with waitress (separate process)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("FINORA_LOCAL_WORKSPACE", "0")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5099)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--products", type=int, default=3000)
    parser.add_argument("--threads", type=int, default=32)
    parser.add_argument("--no-seed", action="store_true", help="another worker already created the store")
    args = parser.parse_args()

    from flask import g
    from waitress import serve

    from app import app
    from bench_scale import seed
    from extensions import db

    if args.no_seed:
        print("READY", flush=True)
        serve(app, host="127.0.0.1", port=args.port, threads=args.threads, connection_limit=4000, channel_timeout=60,
              backlog=4096, _quiet=True)
        raise SystemExit(0)
    seed(app, args.tenant, args.products)
    with app.test_request_context():
        g.tenant = args.tenant
        from models.system_settings import SystemSettings

        s = SystemSettings.get_settings()
        flags = s.get_ui_flags()
        flags["storefront_v2"] = True
        s.set_ui_flags(flags)
        db.session.commit()
    print("READY", flush=True)
    serve(app, host="127.0.0.1", port=args.port, threads=args.threads, connection_limit=4000, channel_timeout=60,
          backlog=4096, _quiet=True)
