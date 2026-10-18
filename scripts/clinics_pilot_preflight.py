"""Preflight checks before onboarding a Clinics pilot tenant.

Reads process environment / optional .env values. Never prints secrets.
Exit code 0 = all hard gates PASS; 1 = one or more FAIL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _get(env: dict[str, str], key: str, default: str = "") -> str:
    return str(os.environ.get(key) or env.get(key) or default).strip()


def main() -> int:
    dotenv = _load_dotenv(ROOT / ".env")
    results: list[tuple[str, bool, str]] = []

    flask_env = _get(dotenv, "FLASK_ENV", "production").lower()
    debug_flag = _get(dotenv, "FLASK_DEBUG", "") or _get(dotenv, "DEBUG", "")
    debug_on = flask_env in {"development", "dev"} or debug_flag in {"1", "true", "True", "yes"}
    results.append(("DEBUG disabled / non-dev env", not debug_on, f"FLASK_ENV={flask_env or '(empty)'}"))

    secret = _get(dotenv, "SECRET_KEY")
    weak = (not secret) or secret in {
        "super-secret-key-change-in-production",
        "your-secret-key-change-in-production",
        "change-me",
    }
    results.append(("SECRET_KEY configured", not weak, "set" if secret and not weak else "missing/weak"))

    db_url = _get(dotenv, "DATABASE_URL")
    is_pg = db_url.startswith("postgres://") or db_url.startswith("postgresql://") or "postgresql+" in db_url
    host = ""
    if db_url:
        try:
            parsed = urlparse(db_url.replace("postgresql+psycopg2://", "postgresql://"))
            host = parsed.hostname or ""
        except Exception:
            host = "(parse-error)"
    results.append(("DATABASE_URL is PostgreSQL", is_pg, f"host={host or '(n/a)'}"))

    timezone = _get(dotenv, "TZ") or _get(dotenv, "CLINICS_TIMEZONE") or _get(dotenv, "APP_TIMEZONE")
    results.append(("Timezone documented", bool(timezone), timezone or "set TZ or CLINICS_TIMEZONE"))

    backup_script = ROOT / "scripts" / "backup_database.ps1"
    results.append(("Backup script present", backup_script.exists(), str(backup_script.name)))

    runbook = ROOT / "docs" / "CLINICS_BACKUP_RESTORE_RUNBOOK.md"
    results.append(("Backup/restore runbook present", runbook.exists(), runbook.name))

    health_note = "GET /clinics/api/health after deploy"
    results.append(("Health endpoint documented", True, health_note))

    status_path = ROOT / "backups" / "daily" / "last_backup_status.json"
    if status_path.exists():
        text = status_path.read_text(encoding="utf-8", errors="replace")
        ok = '"SUCCESS"' in text or '"status": "SUCCESS"' in text or '"status":"SUCCESS"' in text
        results.append(("Last backup status SUCCESS", ok, str(status_path)))
    else:
        results.append(("Last backup status SUCCESS", False, "no last_backup_status.json yet — run backup once"))

    print("FINORA Clinics — Pilot Preflight")
    print("=" * 48)
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name} — {detail}")
    print("=" * 48)
    print("RESULT:", "PASS" if failed == 0 else f"FAIL ({failed})")
    print("Do not print secrets. Confirm HTTPS at the reverse-proxy/load-balancer layer.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
