"""Phase H — PostgreSQL backup → restore → app smoke (hard gate).

Requires CLINICS_TEST_POSTGRES_URL and pg_dump/psql on PATH (or standard install paths).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from flask import Flask
from sqlalchemy import text

from extensions import db

ARTIFACTS = Path(__file__).resolve().parents[1] / "tests" / "_artifacts" / "backup_restore"


def _url():
    return os.environ.get("CLINICS_TEST_POSTGRES_URL")


def _parse_sqlalchemy_url(url: str) -> dict:
    # postgresql+psycopg2://user:pass@host:port/db
    cleaned = url.replace("postgresql+psycopg2://", "postgresql://").replace("postgres+psycopg2://", "postgresql://")
    parsed = urlparse(cleaned)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "database": unquote((parsed.path or "/").lstrip("/")),
    }


def _find_bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for version in ("18", "17", "16", "15"):
        candidate = Path(rf"C:\Program Files\PostgreSQL\{version}\bin\{name}.exe")
        if candidate.exists():
            return str(candidate)
    return None


@pytest.fixture(scope="module")
def pg_backup_app():
    url = _url()
    if not url:
        pytest.skip("CLINICS_TEST_POSTGRES_URL is required for backup/restore gate")
    pg_dump = _find_bin("pg_dump")
    psql = _find_bin("psql")
    if not pg_dump or not psql:
        pytest.skip("pg_dump/psql not available for backup/restore gate")

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="clinics-backup-restore",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401

    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        db.create_all()
        from modules.clinics import service
        from modules.clinics.schema import ensure_clinics_schema
        from modules.clinics.service_specialties import seed_default_specialties

        ensure_clinics_schema()
        seed_default_specialties(1)
        patient = service.create_patient(1, {"full_name": "مريض نسخ احتياطي", "phone": "07701234567"})
        doctor = service.create_doctor(1, {"full_name": "د. نسخ"})
        visit = service.create_walkin_visit(1, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        service.save_vitals(1, visit["id"], {"blood_pressure": "120/80"}, actor_id=1)
        db.session.commit()
        counts = {
            "patients": service.list_patients(1) if False else None,
        }
        from modules.clinics.models import ClinicPatient, ClinicVisit

        counts = {
            "patients": ClinicPatient.query.filter_by(tenant_id=1).count(),
            "visits": ClinicVisit.query.filter_by(tenant_id=1).count(),
        }

    yield {"app": app, "url": url, "pg_dump": pg_dump, "psql": psql, "counts": counts}

    with app.app_context():
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))


def test_postgres_backup_restore_preserves_counts(pg_backup_app):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # pg_dump on Windows can fail on non-ASCII project paths — dump to TEMP then copy evidence.
    dump_path = Path(os.environ.get("TEMP") or "/tmp") / f"clinics_rc_backup_{stamp}.sql"
    meta = _parse_sqlalchemy_url(pg_backup_app["url"])
    env = os.environ.copy()
    if meta["password"]:
        env["PGPASSWORD"] = meta["password"]

    dump_cmd = [
        pg_backup_app["pg_dump"],
        "-h", meta["host"],
        "-p", meta["port"],
        "-U", meta["user"],
        "-d", meta["database"],
        "--no-owner",
        "--no-acl",
        "-f", str(dump_path),
    ]
    started = time.time()
    dump_result = subprocess.run(dump_cmd, check=False, env=env, capture_output=True, text=True)
    if dump_result.returncode != 0:
        pytest.fail(f"pg_dump failed: {dump_result.stderr or dump_result.stdout}")
    dump_seconds = time.time() - started
    assert dump_path.exists() and dump_path.stat().st_size > 1000
    # Client tools may be newer than the server; strip unsupported SET GUCs.
    cleaned = dump_path.read_text(encoding="utf-8", errors="replace").splitlines()
    cleaned = [
        line
        for line in cleaned
        if "transaction_timeout" not in line
    ]
    dump_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    evidence_copy = ARTIFACTS / dump_path.name
    evidence_copy.write_bytes(dump_path.read_bytes())

    app = pg_backup_app["app"]
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))

    restore_cmd = [
        pg_backup_app["psql"],
        "-h", meta["host"],
        "-p", meta["port"],
        "-U", meta["user"],
        "-d", meta["database"],
        "-v", "ON_ERROR_STOP=1",
        "-f", str(dump_path),
    ]
    started = time.time()
    restore_result = subprocess.run(restore_cmd, check=False, env=env, capture_output=True, text=True)
    if restore_result.returncode != 0:
        pytest.fail(f"psql restore failed: {restore_result.stderr or restore_result.stdout}")
    restore_seconds = time.time() - started

    with app.app_context():
        from modules.clinics.models import ClinicPatient, ClinicVisit
        from modules.clinics.schema import SCHEMA_VERSION, ensure_clinics_schema

        ensure_clinics_schema()
        assert ClinicPatient.query.filter_by(tenant_id=1).count() == pg_backup_app["counts"]["patients"]
        assert ClinicVisit.query.filter_by(tenant_id=1).count() == pg_backup_app["counts"]["visits"]
        assert SCHEMA_VERSION.startswith("clinics-v")

    evidence = ARTIFACTS / "last_restore_evidence.txt"
    evidence.write_text(
        "\n".join(
            [
                f"backup_file={evidence_copy.name}",
                f"backup_bytes={evidence_copy.stat().st_size}",
                f"dump_seconds={dump_seconds:.2f}",
                f"restore_seconds={restore_seconds:.2f}",
                f"patients={pg_backup_app['counts']['patients']}",
                f"visits={pg_backup_app['counts']['visits']}",
            ]
        ),
        encoding="utf-8",
    )
