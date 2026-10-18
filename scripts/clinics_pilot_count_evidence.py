"""Print aggregate Clinics table counts for backup/restore evidence.

Uses DATABASE_URL from the environment or .env. Never prints connection
secrets or patient-identifying rows — counts only.

Usage (against disposable or read-only ops DB):

    py scripts/clinics_pilot_count_evidence.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

TABLES = [
    "tenant",
    "clinic_patient",
    "clinic_doctor",
    "clinic_appointment",
    "clinic_visit",
    "clinic_invoice",
    "clinic_payment",
    "clinic_inventory_item",
]


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


def main() -> int:
    dotenv = _load_dotenv(ROOT / ".env")
    url = (os.environ.get("DATABASE_URL") or dotenv.get("DATABASE_URL") or "").strip()
    if not url:
        print("FAIL: DATABASE_URL not set")
        return 1
    if not (url.startswith("postgres://") or url.startswith("postgresql://") or "postgresql+" in url):
        print("FAIL: DATABASE_URL must be PostgreSQL for pilot evidence")
        return 1

    try:
        parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
        host = parsed.hostname or "?"
        dbname = (parsed.path or "/").lstrip("/") or "?"
    except Exception:
        host, dbname = "?", "?"

    print("FINORA Clinics — count evidence (no PHI)")
    print(f"host={host} database={dbname}")
    print("-" * 40)

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("FAIL: sqlalchemy required")
        return 1

    engine = create_engine(url)
    with engine.connect() as conn:
        for table in TABLES:
            try:
                n = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                print(f"{table}: {n}")
            except Exception as exc:
                print(f"{table}: (missing or error — {type(exc).__name__})")
    print("-" * 40)
    print("Copy counts into docs/CLINICS_LIVE_PILOT_EVIDENCE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
