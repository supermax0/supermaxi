"""Phase G live browser smoke — Cardiology + Phase F/E hardening."""
from __future__ import annotations

import os
import socket
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest
from flask import Flask, g, session
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from extensions import db

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests" / "_artifacts" / "specialty_browser_smoke"

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
def specialty_live(tmp_path_factory):
    os.environ["DISABLE_CLINICS_SCHEDULER"] = "1"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path_factory.mktemp("clinic-specialty") / "specialty_smoke.sqlite"

    app = Flask(
        "specialty_browser_smoke",
        root_path=str(ROOT),
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}?check_same_thread=False",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="specialty-browser-smoke",
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
        from modules.clinics.service_cardiology import create_ecg, create_echo, upsert_cardiology_profile
        from modules.clinics.service_gynecology import add_observation, create_pregnancy, upsert_gynecology_profile
        from modules.clinics.service_internal_medicine import create_chronic_condition, upsert_patient_medication

        tenant = Tenant(name="عيادة تخصصات", business_type="clinics", is_active=True)
        db.session.add(tenant)
        db.session.flush()

        owner = Employee(
            name="مالك",
            username="spec-owner",
            password="x",
            role="admin",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        doctor_emp = Employee(
            name="طبيب",
            username="spec-doctor",
            password="x",
            role="employee",
            is_active=True,
            tenant_id=tenant.id,
            language="ar",
        )
        db.session.add_all([owner, doctor_emp])
        db.session.flush()

        specialties = seed_default_specialties(tenant.id)
        by_code = {s["code"]: s for s in specialties}
        doctor = service.create_doctor(
            tenant.id,
            {
                "full_name": "د. متعدد",
                "primary_specialty_id": by_code["cardiology"]["id"],
                "specialty_ids": [
                    by_code["cardiology"]["id"],
                    by_code["internal_medicine"]["id"],
                    by_code["obstetrics_gynecology"]["id"],
                    by_code["dentistry"]["id"],
                    by_code["pediatrics"]["id"],
                ],
                "employee_id": doctor_emp.id,
            },
        )

        cardio_patient = service.create_patient(
            tenant.id, {"full_name": "مريض قلب", "phone": "07701110001", "allergies": "بنسلين"}
        )
        cardio_visit = service.create_walkin_visit(
            tenant.id,
            {
                "patient_id": cardio_patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": by_code["cardiology"]["id"],
            },
        )
        upsert_cardiology_profile(
            tenant.id,
            cardio_patient["id"],
            {"smoking_status": "former", "family_cardiac_history": "أخ CAD"},
            actor_id=doctor_emp.id,
        )
        create_chronic_condition(
            tenant.id,
            cardio_patient["id"],
            {"condition_code": "coronary_artery_disease", "condition_name": "CAD", "status": "active"},
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        create_ecg(
            tenant.id,
            cardio_patient["id"],
            {"visit_id": cardio_visit["id"], "heart_rate": 68, "rhythm": "sinus", "interpretation": "طبيعي"},
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        create_echo(
            tenant.id,
            cardio_patient["id"],
            {"visit_id": cardio_visit["id"], "lvef_percent": 58, "impression": "وظيفة محفوظة"},
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        service.save_vitals(
            tenant.id,
            cardio_visit["id"],
            {"blood_pressure": "128/78", "heart_rate": 68, "weight_kg": 84},
            actor_id=doctor_emp.id,
        )

        im_patient = service.create_patient(tenant.id, {"full_name": "مريض باطنية", "phone": "07701110002"})
        im_visit = service.create_walkin_visit(
            tenant.id,
            {
                "patient_id": im_patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": by_code["internal_medicine"]["id"],
            },
        )
        create_chronic_condition(
            tenant.id,
            im_patient["id"],
            {"condition_code": "diabetes", "condition_name": "السكري", "status": "active"},
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        upsert_patient_medication(
            tenant.id,
            im_patient["id"],
            {"drug_name": "ميتفورمين", "dose_text": "500mg", "status": "active"},
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        service.save_vitals(
            tenant.id, im_visit["id"], {"blood_pressure": "130/80", "blood_glucose": 120}, actor_id=doctor_emp.id
        )

        gyn_patient = service.create_patient(
            tenant.id,
            {"full_name": "مريضة نسائية", "phone": "07701110003", "date_of_birth": date(1992, 2, 2).isoformat()},
        )
        gyn_visit = service.create_walkin_visit(
            tenant.id,
            {
                "patient_id": gyn_patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": by_code["obstetrics_gynecology"]["id"],
            },
        )
        upsert_gynecology_profile(tenant.id, gyn_patient["id"], {"cycle_regular": True}, actor_id=doctor_emp.id)
        preg = create_pregnancy(
            tenant.id,
            gyn_patient["id"],
            {
                "lmp_date": (date.today() - timedelta(days=90)).isoformat(),
                "use_suggested_edd": True,
                "gravida_at_start": 1,
            },
            actor_id=doctor_emp.id,
            doctor_id=doctor["id"],
        )
        add_observation(
            tenant.id,
            preg["id"],
            {"visit_id": gyn_visit["id"], "clinical_notes": "متابعة طبيعية", "fetal_heart_rate": 145},
            actor_id=doctor_emp.id,
        )

        dental_patient = service.create_patient(tenant.id, {"full_name": "مريض أسنان", "phone": "07701110004"})
        dental_visit = service.create_walkin_visit(
            tenant.id,
            {
                "patient_id": dental_patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": by_code["dentistry"]["id"],
            },
        )
        from modules.clinics.service_dental import upsert_tooth_finding
        from modules.clinics.service_dental_treatment import add_plan_item, create_plan

        upsert_tooth_finding(
            tenant.id,
            dental_visit["id"],
            "16",
            {"status": "caries", "notes": "حفر"},
            actor_id=doctor_emp.id,
        )
        plan = create_plan(
            tenant.id,
            dental_patient["id"],
            {"doctor_id": doctor["id"], "source_visit_id": dental_visit["id"], "name": "خطة تجريبية"},
            actor_id=doctor_emp.id,
        )
        plan_id = plan.get("id") or (plan.get("plan") or {}).get("id")
        add_plan_item(
            tenant.id,
            plan_id,
            {"tooth_number": "16", "title": "حشو", "status": "planned"},
            actor_id=doctor_emp.id,
        )

        ped_patient = service.create_patient(
            tenant.id,
            {
                "full_name": "طفل تجريبي",
                "phone": "07701110005",
                "date_of_birth": (date.today() - timedelta(days=800)).isoformat(),
            },
        )
        ped_visit = service.create_walkin_visit(
            tenant.id,
            {
                "patient_id": ped_patient["id"],
                "doctor_id": doctor["id"],
                "specialty_id": by_code["pediatrics"]["id"],
            },
        )
        from modules.clinics.service_pediatrics import add_vaccination, upsert_pediatric_profile

        upsert_pediatric_profile(
            tenant.id,
            ped_patient["id"],
            {"gestational_age_weeks": 39, "delivery_type": "vaginal", "birth_weight": 3.2},
            actor_id=doctor_emp.id,
        )
        service.save_vitals(
            tenant.id,
            ped_visit["id"],
            {"weight_kg": 11.5, "height_cm": 80, "head_circumference_cm": 47},
            actor_id=doctor_emp.id,
        )
        add_vaccination(
            tenant.id,
            ped_patient["id"],
            {"vaccine_name": "MMR", "status": "recorded", "administered_date": date.today().isoformat()},
            actor_id=doctor_emp.id,
        )

        db.session.commit()
        state.update(
            {
                "tenant_id": tenant.id,
                "owner_id": owner.id,
                "doctor_emp_id": doctor_emp.id,
                "doctor_id": doctor["id"],
                "cardio_patient_id": cardio_patient["id"],
                "cardio_visit_id": cardio_visit["id"],
                "im_patient_id": im_patient["id"],
                "im_visit_id": im_visit["id"],
                "gyn_patient_id": gyn_patient["id"],
                "gyn_visit_id": gyn_visit["id"],
                "dental_patient_id": dental_patient["id"],
                "dental_visit_id": dental_visit["id"],
                "ped_patient_id": ped_patient["id"],
                "ped_visit_id": ped_visit["id"],
                "perm_by_employee": {doctor_emp.id: set(DOCTOR_PERMS)},
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


def _open_patient_specialty(page, base: str, patient_id: int, section_button, root_selector: str, expected: str):
    """Navigate patient profile specialty hub; one reload retry for SQLite/browser flakes."""
    page.goto(
        f"{base}/clinics/patients/{patient_id}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)

    def _attempt():
        page.get_by_role("button", name="السجل السريري").click()
        if isinstance(section_button, str) and section_button.startswith("["):
            page.locator(section_button).click()
        else:
            page.get_by_role("button", name=section_button).click()
        expect(page.locator(root_selector)).to_contain_text(expected, timeout=30000)

    try:
        _attempt()
    except AssertionError:
        page.reload(wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector("#cxRoot", timeout=25000)
        _attempt()


def test_cardiology_workspace_and_profile_browser(specialty_live):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    vid = specialty_live["state"]["cardio_visit_id"]
    page.goto(f"{specialty_live['base']}/clinics/doctor/{vid}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.get_by_role("button", name="القلب والأوعية").click()
    root = page.locator("#cardiologyToolsRoot")
    expect(root).to_contain_text("ECG", timeout=20000)
    expect(root).to_contain_text("sinus")
    expect(root).to_contain_text("58")
    _open_patient_specialty(
        page,
        specialty_live["base"],
        specialty_live["state"]["cardio_patient_id"],
        '[data-profile-section="cardiology"]',
        "#ppCardioRoot",
        "ECG",
    )
    expect(page.locator("#ppCardioRoot")).to_contain_text("sinus", timeout=10000)
    context.close()


def test_internal_medicine_browser_hardening(specialty_live):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(
        f"{specialty_live['base']}/clinics/doctor/{specialty_live['state']['im_visit_id']}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.get_by_role("button", name="الباطنية والأمراض المزمنة").click()
    root = page.locator("#internalMedicineToolsRoot")
    expect(root).to_contain_text("السكري", timeout=20000)
    expect(root).to_contain_text("ميتفورمين")
    _open_patient_specialty(
        page,
        specialty_live["base"],
        specialty_live["state"]["im_patient_id"],
        "الباطنية والأمراض المزمنة",
        "#ppImRoot",
        "السكري",
    )
    context.close()


def test_gynecology_browser_hardening(specialty_live):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(
        f"{specialty_live['base']}/clinics/doctor/{specialty_live['state']['gyn_visit_id']}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.get_by_role("button", name="النسائية والتوليد").click()
    root = page.locator("#gynecologyToolsRoot")
    expect(root).to_contain_text("حمل", timeout=20000)
    _open_patient_specialty(
        page,
        specialty_live["base"],
        specialty_live["state"]["gyn_patient_id"],
        "النسائية والتوليد",
        "#ppGynRoot",
        "LMP",
    )
    context.close()


def test_dentistry_browser_hardening(specialty_live):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(
        f"{specialty_live['base']}/clinics/doctor/{specialty_live['state']['dental_visit_id']}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.locator('#docTabs button[data-tab="treatment"]').click()
    expect(page.locator("#dentalTreatmentPlanRoot")).to_be_visible(timeout=20000)
    page.goto(
        f"{specialty_live['base']}/clinics/patients/{specialty_live['state']['dental_patient_id']}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.get_by_role("button", name="السجل السريري").click()
    page.get_by_role("button", name="الأسنان").click()
    expect(page.locator("#ppContent")).to_contain_text("خطة", timeout=25000)
    context.close()


def test_pediatrics_browser_hardening(specialty_live):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    page.goto(
        f"{specialty_live['base']}/clinics/doctor/{specialty_live['state']['ped_visit_id']}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    page.wait_for_selector("#cxRoot", timeout=25000)
    page.get_by_role("button", name="طب الأطفال").click()
    root = page.locator("#pediatricToolsRoot")
    expect(root).to_contain_text("MMR", timeout=20000)
    _open_patient_specialty(
        page,
        specialty_live["base"],
        specialty_live["state"]["ped_patient_id"],
        "طب الأطفال",
        "#ppPedRoot",
        "MMR",
    )
    context.close()
