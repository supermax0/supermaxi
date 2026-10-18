"""Phase UX final closure — live browser role / hub / workspace smoke."""
from __future__ import annotations

import os
import re
import socket
import threading
from pathlib import Path

import pytest
from flask import Flask, g, session
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from extensions import db

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests" / "_artifacts" / "ux_role_smoke"

OWNER_PERMS = None  # admin short-circuit
RECEPTION_PERMS = {
    "clinics_dashboard",
    "clinics_reception",
    "clinics_appointments",
    "clinics_patients",
    "clinics_billing",
    "clinics_visits",
}
DOCTOR_PERMS = {
    "clinics_dashboard",
    "clinics_patients",
    "clinics_visits",
    "clinics_clinical",
    "clinics_appointments",
    "clinics_billing",
    "clinics_admin",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def ux_live(tmp_path_factory):
    os.environ["DISABLE_CLINICS_SCHEDULER"] = "1"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path_factory.mktemp("clinic-roles") / "ux_role_smoke.sqlite"

    app = Flask(
        "ux_role_smoke",
        root_path=str(ROOT),
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}?check_same_thread=False",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="ux-role-smoke",
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

    state = {"employee_id": None, "perm_by_employee": {}}

    with app.app_context():
        db.create_all()
        from models.employee import Employee
        from models.tenant import Tenant
        from modules.clinics import service
        from modules.clinics.service_specialties import seed_default_specialties

        tenant = Tenant(name="عيادة UX", business_type="clinics", is_active=True)
        db.session.add(tenant)
        db.session.flush()

        owner = Employee(
            name="مالك",
            username="ux-owner",
            password="x",
            role="admin",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        db.session.add(owner)
        db.session.flush()

        reception = Employee(
            name="استقبال",
            username="ux-reception",
            password="x",
            role="employee",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        doctor_emp = Employee(
            name="طبيب",
            username="ux-doctor",
            password="x",
            role="employee",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        db.session.add_all([reception, doctor_emp])
        db.session.flush()

        specialties = seed_default_specialties(tenant.id)
        ped = next(s for s in specialties if s["code"] == "pediatrics")
        dentist = next(s for s in specialties if s["code"] == "dentistry")
        doctor = service.create_doctor(
            tenant.id,
            {
                "full_name": "د. مرتبط",
                "primary_specialty_id": ped["id"],
                "specialty_ids": [ped["id"], dentist["id"]],
                "employee_id": doctor_emp.id,
            },
        )
        patient = service.create_patient(tenant.id, {"full_name": "مريض UX", "phone": "07709998877"})
        visit = service.create_walkin_visit(
            tenant.id,
            {"patient_id": patient["id"], "doctor_id": doctor["id"], "specialty_id": ped["id"]},
        )
        db.session.commit()
        state.update(
            {
                "tenant_id": tenant.id,
                "owner_id": owner.id,
                "reception_id": reception.id,
                "doctor_emp_id": doctor_emp.id,
                "doctor_id": doctor["id"],
                "patient_id": patient["id"],
                "visit_id": visit["id"],
                "perm_by_employee": {
                    reception.id: set(RECEPTION_PERMS),
                    doctor_emp.id: set(DOCTOR_PERMS),
                },
            }
        )

    from models.employee import Employee as EmpModel
    from modules.clinics import service_dashboard

    _orig_has = EmpModel.has_permission
    _orig_perms = service_dashboard._employee_permissions

    def _has_permission(self, name):
        perms = state["perm_by_employee"].get(self.id)
        if perms is not None:
            return name in perms
        return _orig_has(self, name)

    def _employee_permissions(employee):
        if not employee:
            return []
        if employee.role == "admin":
            return _orig_perms(employee)
        perms = state["perm_by_employee"].get(employee.id)
        if perms is not None:
            return sorted(perms)
        return _orig_perms(employee)

    EmpModel.has_permission = _has_permission
    service_dashboard._employee_permissions = _employee_permissions

    @app.before_request
    def _auth_session():
        session["user_id"] = state["employee_id"]
        session["tenant_id"] = state["tenant_id"]
        session["business_type"] = "clinics"
        session["lang"] = "ar"
        g.clinics_tenant_id = state["tenant_id"]

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def as_persona(persona: str):
        if persona == "owner":
            state["employee_id"] = state["owner_id"]
        elif persona == "reception":
            state["employee_id"] = state["reception_id"]
        elif persona == "doctor":
            state["employee_id"] = state["doctor_emp_id"]
        else:
            raise ValueError(persona)

    with sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except Exception:
            browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield {
            "base": f"http://127.0.0.1:{port}",
            "browser": browser,
            "as_persona": as_persona,
            "state": state,
        }
        browser.close()
    server.shutdown()
    EmpModel.has_permission = _orig_has
    service_dashboard._employee_permissions = _orig_perms


def _visible_nav_keys(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-nav-key]'))
            .filter(el => !el.hidden && !el.classList.contains('cx-nav-hidden'))
            .map(el => el.getAttribute('data-nav-key'))"""
    )


def _wait_nav(page):
    page.wait_for_function(
        "() => document.documentElement.dataset.cxPersona",
        timeout=25000,
    )


def test_owner_sidebar_smoke(ux_live):
    ux_live["as_persona"]("owner")
    context = ux_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(f"{ux_live['base']}/clinics/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("#cxRoot", timeout=20000)
    _wait_nav(page)
    keys = set(_visible_nav_keys(page))
    assert "dashboard" in keys
    assert "billing" in keys or "cash" in keys
    assert "inventory" in keys
    assert "doctors" in keys or "settings" in keys
    page.goto(
        f"{ux_live['base']}/clinics/patients/{ux_live['state']['patient_id']}",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("[data-profile-hub]", timeout=20000)
    hubs = page.locator("[data-profile-hub]").all_text_contents()
    assert any("نظرة عامة" in h for h in hubs)
    page.screenshot(path=str(ARTIFACTS / "owner_dashboard.png"), full_page=True)
    context.close()


def test_doctor_sidebar_and_workspace_smoke(ux_live):
    ux_live["as_persona"]("doctor")
    context = ux_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(f"{ux_live['base']}/clinics/visits", wait_until="domcontentloaded", timeout=30000)
    _wait_nav(page)
    assert page.evaluate("() => document.documentElement.dataset.cxPersona") == "doctor"
    keys = set(_visible_nav_keys(page))
    assert "visits" in keys or "patients" in keys
    for banned in ("purchases", "suppliers", "cash", "settlements", "inventory", "doctors", "settings"):
        assert banned not in keys, f"doctor should hide {banned}, got {keys}"
    page.goto(
        f"{ux_live['base']}/clinics/doctor/{ux_live['state']['visit_id']}",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#docTabs", timeout=20000)
    expect(page.locator(".cx-doctor-quick")).to_be_visible()
    page.locator('[data-jump-tab="rx"]').click()
    expect(page.locator("#tab-rx")).to_have_class(re.compile(r"is-active"))
    page.locator('[data-jump-tab="clinical"]').click()
    expect(page.locator("#tab-clinical")).to_have_class(re.compile(r"is-active"))
    page.screenshot(path=str(ARTIFACTS / "doctor_workspace.png"), full_page=True)
    context.close()


def test_reception_sidebar_smoke(ux_live):
    ux_live["as_persona"]("reception")
    context = ux_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(f"{ux_live['base']}/clinics/reception", wait_until="domcontentloaded", timeout=30000)
    _wait_nav(page)
    assert page.evaluate("() => document.documentElement.dataset.cxPersona") == "reception"
    keys = set(_visible_nav_keys(page))
    assert "reception" in keys
    assert "patients" in keys
    for banned in ("clinical", "doctors", "inventory", "settings", "rooms"):
        assert banned not in keys, f"reception should hide {banned}, got {keys}"
    page.screenshot(path=str(ARTIFACTS / "reception.png"), full_page=True)
    context.close()


@pytest.mark.parametrize("width", [390, 375])
@pytest.mark.parametrize("persona", ["doctor", "reception"])
def test_mobile_persona_nav(ux_live, width, persona):
    ux_live["as_persona"](persona)
    context = ux_live["browser"].new_context(locale="ar-IQ", viewport={"width": width, "height": 844})
    page = context.new_page()
    page.goto(f"{ux_live['base']}/clinics/", wait_until="domcontentloaded", timeout=30000)
    _wait_nav(page)
    mobile_keys = page.evaluate(
        """() => Array.from(document.querySelectorAll('.cx-mobile-nav [data-mobile-key]:not([hidden])'))
            .map(el => el.getAttribute('data-mobile-key'))"""
    )
    assert 1 <= len(mobile_keys) <= 4
    overflow = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2")
    assert overflow
    if persona == "doctor":
        assert "reception" not in mobile_keys
    page.screenshot(path=str(ARTIFACTS / f"mobile_{persona}_{width}.png"), full_page=True)
    context.close()


def test_patient_hub_tabs_smoke(ux_live):
    ux_live["as_persona"]("owner")
    context = ux_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(
        f"{ux_live['base']}/clinics/patients/{ux_live['state']['patient_id']}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector("[data-profile-hub]", timeout=20000)
    expected = ["نظرة عامة", "المواعيد", "السجل", "العلاج", "الملفات", "المالية"]
    text = " ".join(page.locator("[data-profile-hub]").all_text_contents())
    for fragment in expected:
        assert fragment in text, f"missing hub fragment {fragment} in {text!r}"
    page.locator('[data-profile-hub="clinical"]').click()
    page.wait_for_selector("[data-profile-section]", timeout=10000)
    sections = page.locator("[data-profile-section]").all_text_contents()
    joined = " ".join(sections)
    assert "الأسنان" in joined or "طب الأطفال" in joined or "السجل" in joined
    page.screenshot(path=str(ARTIFACTS / "patient_hub.png"), full_page=True)
    context.close()
