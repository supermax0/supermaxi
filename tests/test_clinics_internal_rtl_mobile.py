"""Internal clinics RTL / mobile QA — real browser against authenticated workspace.

Critical pages at desktop/tablet/mobile widths. Records screenshots under
tests/_artifacts/internal_rtl_mobile/.
"""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

import pytest
from flask import Flask, g, session
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from extensions import db

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests" / "_artifacts" / "internal_rtl_mobile"

CRITICAL_PATHS = [
    "/clinics/",
    "/clinics/reception",
    "/clinics/appointments",
    "/clinics/queue",
    "/clinics/patients",
    "/clinics/visits",
    "/clinics/clinical",
    "/clinics/labs",
    "/clinics/radiology",
    "/clinics/followups",
    "/clinics/procedures",
    "/clinics/billing",
    "/clinics/inventory",
    "/clinics/doctors",
    "/clinics/specialties",
    "/clinics/services",
    "/clinics/reports",
    "/clinics/settings",
]

VIEWPORTS = [
    (1920, 1080),
    (1366, 768),
    (1024, 768),
    (768, 1024),
    (430, 932),
    (390, 844),
    (375, 812),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_workspace(tmp_path_factory):
    os.environ["DISABLE_CLINICS_SCHEDULER"] = "1"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path_factory.mktemp("clinic-rtl") / "rtl_workspace.sqlite"

    app = Flask(
        "rtl_mobile_e2e",
        root_path=str(ROOT),
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}?check_same_thread=False",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="rtl-mobile-e2e",
    )
    if "sqlalchemy" in app.extensions:
        del app.extensions["sqlalchemy"]
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401
    from modules.clinics import init_clinics
    from routes.features_api import features_api_bp

    app.register_blueprint(features_api_bp)
    init_clinics(app)

    @app.context_processor
    def _inject_i18n():
        from modules.clinics.guards import can_use_clinics

        return {"_": lambda key, **kwargs: key, "current_lang": "ar",
                "is_clinics_business": True,
                "business_allows": lambda key: can_use_clinics(None if key == "clinics" else key)}

    employee_id = None
    patient_id = None
    visit_id = None
    tenant_id = None
    with app.app_context():
        db.create_all()
        from models.employee import Employee
        from models.tenant import Tenant
        from modules.clinics import service
        from modules.clinics.service_specialties import seed_default_specialties

        tenant = Tenant(name="عيادة RTL", business_type="clinics", is_active=True)
        db.session.add(tenant)
        db.session.flush()
        tenant_id = tenant.id
        emp = Employee(
            name="مدير RTL",
            username="rtl-admin",
            password="x",
            role="admin",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        db.session.add(emp)
        db.session.flush()
        employee_id = emp.id
        seed_default_specialties(tenant.id)
        doctor = service.create_doctor(tenant.id, {"full_name": "د. اختبار"})
        patient = service.create_patient(tenant.id, {"full_name": "مريض RTL", "phone": "07701112233"})
        visit = service.create_walkin_visit(tenant.id, {"patient_id": patient["id"], "doctor_id": doctor["id"]})
        patient_id = patient["id"]
        visit_id = visit["id"]
        db.session.commit()

    @app.before_request
    def _auth_session():
        session["user_id"] = employee_id
        session["tenant_id"] = tenant_id
        session["business_type"] = "clinics"
        session["lang"] = "ar"
        g.clinics_tenant_id = tenant_id

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except Exception:
            browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield {
            "base": f"http://127.0.0.1:{port}",
            "browser": browser,
            "patient_id": patient_id,
            "visit_id": visit_id,
        }
        browser.close()
    server.shutdown()


def _no_overflow(page):
    metrics = page.evaluate(
        """() => {
            const app = document.querySelector('.cx-app');
            return {
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                dir: document.documentElement.getAttribute('dir') || '',
                rtl: getComputedStyle(document.documentElement).direction,
                appDir: app ? (app.getAttribute('dir') || getComputedStyle(app).direction) : ''
            };
        }"""
    )
    assert metrics["scrollWidth"] <= metrics["clientWidth"] + 2, metrics
    assert metrics["dir"] == "rtl" or metrics["rtl"] == "rtl", metrics
    assert metrics["appDir"] == "rtl", metrics
    return metrics


# Full matrix on primary widths; smoke the rest on shell pages only.
PRIMARY_VIEWPORTS = {(1920, 1080), (1366, 768), (375, 812)}
SMOKE_PATHS = {"/clinics/", "/clinics/reception", "/clinics/specialties", "/clinics/billing"}


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_internal_pages_rtl_no_overflow(live_workspace, width, height):
    context = live_workspace["browser"].new_context(
        locale="ar-IQ",
        viewport={"width": width, "height": height},
    )
    page = context.new_page()
    if (width, height) in PRIMARY_VIEWPORTS:
        paths = list(CRITICAL_PATHS)
        paths.append(f"/clinics/patients/{live_workspace['patient_id']}")
        paths.append(f"/clinics/doctor/{live_workspace['visit_id']}")
    else:
        paths = list(SMOKE_PATHS)
    failures = []
    for path in paths:
        page.goto(f"{live_workspace['base']}{path}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(150)
        assert page.locator("body").count() == 1
        try:
            _no_overflow(page)
        except AssertionError as exc:
            failures.append(f"{path}@{width}: {exc}")
            safe = path.strip("/").replace("/", "_") or "root"
            page.screenshot(path=str(ARTIFACTS / f"fail_{safe}_{width}.png"), full_page=True)
        else:
            if width in (1920, 375) and path in ("/clinics/", "/clinics/specialties", "/clinics/reception"):
                safe = path.strip("/").replace("/", "_") or "root"
                page.screenshot(path=str(ARTIFACTS / f"ok_{safe}_{width}.png"), full_page=True)
    context.close()
    assert not failures, "\n".join(failures)
