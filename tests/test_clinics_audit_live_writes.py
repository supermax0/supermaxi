"""Real HTTP/browser persistence audit; synthetic records, isolated SQLite.

Unlike the component fixtures, these tests do not intercept clinic API calls.
Authentication/personas and initial records come from the existing live fixture.
"""
import importlib.util
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests/_artifacts/clinics_audit_20260907/live_writes"
_spec = importlib.util.spec_from_file_location(
    "_audit_specialty_fixture", ROOT / "tests/test_clinics_specialty_browser_smoke.py"
)
_source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_source)
_source.ARTIFACTS = ARTIFACTS
specialty_live = _source.specialty_live


@pytest.fixture()
def live_page(specialty_live, request):
    specialty_live["as_persona"]("doctor")
    context = specialty_live["browser"].new_context(
        locale="ar-IQ", viewport={"width": 1366, "height": 900}
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    page.screenshot(path=str(ARTIFACTS / f"{request.node.name}.png"), full_page=True)
    context.tracing.stop(path=str(ARTIFACTS / f"{request.node.name}.zip"))
    context.close()
    assert not errors, errors


def open_visit(page, live, key, tab):
    page.goto(f"{live['base']}/clinics/doctor/{live['state'][key + '_visit_id']}",
              wait_until="domcontentloaded")
    page.locator("#docTabs").get_by_role("button", name=tab, exact=True).click()


def save(page, suffix):
    with page.expect_response(lambda r: suffix in r.url and r.request.method in ("POST", "PATCH")) as pending:
        page.locator("#cxModalSave").click()
    response = pending.value
    assert response.ok, response.text()
    assert response.json()["ok"], response.text()
    expect(page.locator("#cxModalSave")).not_to_be_visible()
    return response.json()["data"]


def test_internal_medicine_condition_and_medication_survive_reload(live_page, specialty_live):
    page, live = live_page, specialty_live
    open_visit(page, live, "im", "الباطنية والأمراض المزمنة")
    root = page.locator("#internalMedicineToolsRoot")
    root.locator("[data-add-cond]").click()
    page.locator("#imCondCode").select_option("hypertension")
    page.locator("#imCondName").fill("ضغط تجريبي QA 20260907")
    page.locator("#imCondNotes").fill("بيانات اختبار برمجي فقط")
    save(page, "/chronic-conditions")
    root.locator("[data-add-med]").click()
    page.locator("#imMedName").fill("دواء تجريبي QA 20260907")
    page.locator("#imMedDose").fill("جرعة اختبار")
    page.locator("#imMedFreq").fill("تكرار اختبار")
    save(page, "/medications")
    open_visit(page, live, "im", "الباطنية والأمراض المزمنة")
    expect(root).to_contain_text("ضغط تجريبي QA 20260907")
    expect(root).to_contain_text("دواء تجريبي QA 20260907")
    pid = live["state"]["im_patient_id"]
    data = page.request.get(f"{live['base']}/clinics/api/patients/{pid}/chronic-conditions").json()
    assert "ضغط تجريبي QA 20260907" in str(data)


def test_gynecology_observation_survives_reload(live_page, specialty_live):
    page, live = live_page, specialty_live
    open_visit(page, live, "gyn", "النسائية والتوليد")
    root = page.locator("#gynecologyToolsRoot")
    root.locator("[data-add-obs]").click()
    page.locator("#ob_fhr").fill("140")
    page.locator("#ob_pres").fill("وضع تجريبي QA")
    page.locator("#ob_notes").fill("ملاحظة اختبار QA 20260907")
    saved = save(page, "/observations")
    assert saved["fetal_heart_rate"] == 140
    open_visit(page, live, "gyn", "النسائية والتوليد")
    expect(root).to_contain_text("ملاحظة اختبار QA 20260907")
    expect(root).to_contain_text("140")


def test_dental_plan_item_and_invoice_persist(live_page, specialty_live):
    page, live = live_page, specialty_live
    page.goto(f"{live['base']}/clinics/doctor/{live['state']['dental_visit_id']}",
              wait_until="domcontentloaded")
    page.locator('#docTabs [data-tab="treatment"]').click()
    root = page.locator("#dentalTreatmentPlanRoot")
    root.locator("[data-create-plan]").first.click()
    page.locator("#dtpName").fill("خطة اختبار QA 20260907")
    save(page, "/dental-treatment-plans")
    root.locator("[data-add-general]").click()
    page.locator("#dtpTooth").fill("26")
    page.locator("#dtpTitle").fill("علاج تجريبي QA 20260907")
    page.locator("#dtpSessions").fill("2")
    page.locator("#dtpPrice").fill("25000")
    save(page, "/items")
    page.reload(wait_until="domcontentloaded")
    page.locator('#docTabs [data-tab="treatment"]').click()
    expect(root).to_contain_text("علاج تجريبي QA 20260907")
    root.locator("[data-invoice]").click()
    save(page, "/invoice")
    pid = live["state"]["dental_patient_id"]
    result = page.request.get(f"{live['base']}/clinics/api/patients/{pid}/dental-treatment-plans").json()
    assert result["ok"], result
    plan = result["data"]["active_plan"]
    assert plan["plan"]["name"] == "خطة اختبار QA 20260907"
    assert len(plan["items"]) == 1
    assert float(plan["items"][0]["estimated_price"]) == 25000
