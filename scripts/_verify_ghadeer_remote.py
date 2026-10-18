"""Restart production app and confirm the ghadeer tenant exists."""
from __future__ import annotations

import subprocess
import sys

HOST = "root@187.124.29.5"
REMOTE = r"""
set -e
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
cd /var/www/finora/supermaxi
./venv/bin/python - <<'PY'
import os
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER","1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER","1")
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS","1")
from app import app
from models.core.tenant import Tenant as CoreTenant
with app.app_context():
    row = CoreTenant.query.filter_by(slug="ghadeer").first()
    print("TENANT", "OK" if row and row.is_active else "MISSING", getattr(row, "name", None))
PY
test -f /var/www/finora/supermaxi/tenants/profiles/ghadeer.json && echo PROFILE_OK
echo DONE
"""


def main() -> int:
    cmd = [
        "ssh", "-n",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=6",
        HOST,
        REMOTE,
    ]
    return subprocess.run(cmd, timeout=90).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired:
        print("SSH timed out", file=sys.stderr)
        raise SystemExit(124)
