"""Copy the dental provisioner to production and create the Ghadeer tenant."""
from __future__ import annotations

import subprocess
import sys

HOST = "root@187.124.29.5"
APP = "/var/www/finora/supermaxi"

REMOTE = r"""
set -euo pipefail
cp /tmp/provision_dental_clinic.py /var/www/finora/supermaxi/scripts/provision_dental_clinic.py
python3 - <<'PY'
from pathlib import Path
Path("/tmp/run_ghadeer.sh").write_text(
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    "cd /var/www/finora/supermaxi\n"
    "export DISABLE_CLINICS_SCHEDULER=1\n"
    "export DISABLE_PUBLISHER_SCHEDULER=1\n"
    "export FINORA_DISABLE_SCHEDULERS=1\n"
    "./venv/bin/python scripts/provision_dental_clinic.py "
    "--slug ghadeer "
    "--name '\u0639\u064a\u0627\u062f\u0629 \u062f. \u063a\u062f\u064a\u0631 \u0644\u0644\u0623\u0633\u0646\u0627\u0646' "
    "--owner '\u062f. \u063a\u062f\u064a\u0631' "
    "--doctor-name '\u062f. \u063a\u062f\u064a\u0631' "
    "--password 'Ghadeer@Admin2026' "
    "--doctor-password 'Ghadeer@Doctor2026' "
    "--reception-password 'Ghadeer@Rec2026' "
    "--trial-days 90\n",
    encoding="utf-8",
    newline="\n",
)
print("RUNNER_WRITTEN")
PY
chmod +x /tmp/run_ghadeer.sh
bash /tmp/run_ghadeer.sh
"""


def main() -> int:
    cmd = [
        "ssh",
        "-n",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=6",
        HOST,
        REMOTE,
    ]
    print("Connecting to production and provisioning ghadeer...", flush=True)
    completed = subprocess.run(cmd, timeout=240)
    return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired:
        print("SSH timed out", file=sys.stderr)
        raise SystemExit(124)
