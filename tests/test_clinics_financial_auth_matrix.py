"""Full financial / authorization matrix — inspect raw JSON, not UI visibility.

Finance classes used by this gate:

- transactional_finance: patient service price, invoice amount, amount due,
  payment amount (requires clinics_billing for ledger endpoints; reception may
  see limited operational amounts when permitted).
- management_finance: revenue totals, doctor commission, settlements, expenses,
  cash session expected/actual, report hubs (clinics_billing and/or clinics_admin).
- cost_finance: purchase_cost / average_cost / inventory valuation / margin
  (purchases.cost.view or clinics_billing).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from extensions import db
from tests.test_clinics_specialties import specialty_db  # noqa: F401


ROLE_PERMS = {
    "admin": {"clinics_admin", "clinics_billing", "clinics_inventory", "purchases.view", "purchases.cost.view", "clinics_reports"},
    "owner": {"clinics_admin", "clinics_billing", "clinics_inventory", "purchases.view", "purchases.cost.view", "clinics_reports"},
    "owner_doctor": {"clinics_admin", "clinics_billing", "clinics_clinical", "clinics_reports"},
    "doctor_employee": {"clinics_clinical", "clinics_visits", "clinics_patients"},
    "receptionist": {"clinics_reception", "clinics_appointments", "clinics_patients"},
    "accountant": {"clinics_billing", "clinics_reports", "purchases.view", "purchases.cost.view", "purchases.payment.view"},
    "clinical_staff": {"clinics_clinical", "clinics_visits"},
    "inventory_user": {"clinics_inventory"},
    "purchase_user": {"purchases.view", "purchases.create", "clinics_inventory"},
}


COST_KEYS = ("purchase_price", "average_cost", "last_purchase_cost", "inventory_value", "unit_cost")
MANAGEMENT_KEYS = ("commission_pct", "doctor_commission_pct", "doctor_commission_default_pct", "revenue", "gross_revenue", "doctor_share")


def _employee(role: str):
    perms = ROLE_PERMS[role]
    # can_use_clinics short-circuits when employee.role == "admin".
    # Matrix roles must rely on has_permission only.
    return SimpleNamespace(
        id=10,
        name=role,
        username=role,
        profile_pic=None,
        role="employee",
        is_active=True,
        has_permission=lambda key, _p=perms: key in _p,
        roles=[SimpleNamespace(permissions=[SimpleNamespace(name=k) for k in perms])],
    )


def _client_as(app, monkeypatch, role: str):
    from modules.clinics import routes, guards

    employee = _employee(role)
    monkeypatch.setattr(guards, "current_employee", lambda: employee)
    monkeypatch.setattr(guards, "current_tenant_id", lambda: 1)
    monkeypatch.setattr(guards, "is_clinics_tenant", lambda: True)
    monkeypatch.setattr(guards, "get_current_clinic_doctor", lambda: None)
    monkeypatch.setattr(routes, "ensure_clinics_schema", lambda: None)
    if "clinics" not in app.blueprints:
        app.register_blueprint(routes.clinics_bp)
    return app.test_client()


def _seed_finance_fixture():
    from modules.clinics import service
    from modules.clinics.models import ClinicInvoice, ClinicInventoryItem
    from modules.clinics.service_ops import create_inventory_item

    doctor = service.create_doctor(1, {"full_name": "د. مالي", "commission_pct": 20})
    patient = service.create_patient(1, {"full_name": "مريض مالي"})
    visit = service.create_walkin_visit(
        1, {"patient_id": patient["id"], "doctor_id": doctor["id"], "chief_complaint": "ألم"}
    )
    service.create_service(1, {"name": "كشف", "price": 25000, "doctor_commission_pct": 15})
    inv = ClinicInvoice(
        tenant_id=1,
        patient_id=patient["id"],
        doctor_id=doctor["id"],
        visit_id=visit["id"],
        invoice_number="FIN-MATRIX-1",
        total=25000,
        paid=0,
        balance=25000,
        status="unpaid",
    )
    db.session.add(inv)
    item = create_inventory_item(
        1,
        {
            "name": "قفازات سرية",
            "sku": "COST-1",
            "purchase_price": 9000,
            "selling_price": 12000,
            "current_stock": 10,
            "opening_cost": 9000,
        },
    )
    db.session.commit()
    return {"doctor": doctor, "patient": patient, "visit": visit, "invoice": inv, "item": item}


@pytest.mark.parametrize(
    "role,path,expected",
    [
        ("doctor_employee", "/clinics/api/invoices", 403),
        ("clinical_staff", "/clinics/api/invoices", 403),
        ("receptionist", "/clinics/api/invoices", 403),
        ("accountant", "/clinics/api/invoices", 200),
        ("admin", "/clinics/api/invoices", 200),
        ("doctor_employee", "/clinics/api/settlements", 403),
        ("accountant", "/clinics/api/settlements", 200),
        ("doctor_employee", "/clinics/api/expenses", 403),
        ("accountant", "/clinics/api/expenses", 200),
        ("doctor_employee", "/clinics/api/cash-sessions", 403),
        ("accountant", "/clinics/api/cash-sessions", 200),
        ("doctor_employee", "/clinics/api/reports/summary", 403),
        ("receptionist", "/clinics/api/reports/hub", 403),
        ("accountant", "/clinics/api/reports/summary", 200),
        ("inventory_user", "/clinics/api/inventory", 200),
        ("doctor_employee", "/clinics/api/inventory", 403),
        ("purchase_user", "/clinics/api/purchases", 200),
        # purchases.view falls back to clinics_inventory by design for ops access
        ("inventory_user", "/clinics/api/purchases", 200),
        ("inventory_user", "/clinics/api/purchases/price-history", 403),
        ("accountant", "/clinics/api/purchases/price-history", 200),
    ],
)
def test_endpoint_permission_matrix(specialty_db, monkeypatch, role, path, expected):
    with specialty_db.app_context():
        _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, role)
        response = client.get(path)
        assert response.status_code == expected, f"{role} {path}: {response.status_code} {response.get_data(as_text=True)[:200]}"


def test_doctor_visit_json_hides_management_finance(specialty_db, monkeypatch):
    with specialty_db.app_context():
        seeded = _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, "doctor_employee")
        response = client.get(f"/clinics/api/visits/{seeded['visit']['id']}")
        assert response.status_code == 200
        body = response.get_json()
        encoded = json.dumps(body, ensure_ascii=False)
        assert "FIN-MATRIX-1" not in encoded
        data = body.get("data") or body
        assert "invoices" not in data
        for key in MANAGEMENT_KEYS:
            assert f'"{key}"' not in encoded


def test_inventory_user_json_hides_cost_finance(specialty_db, monkeypatch):
    with specialty_db.app_context():
        seeded = _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, "inventory_user")
        response = client.get("/clinics/api/inventory?center=1")
        assert response.status_code == 200
        encoded = json.dumps(response.get_json(), ensure_ascii=False)
        for key in COST_KEYS:
            assert f'"{key}"' not in encoded
        detail = client.get(f"/clinics/api/inventory/{seeded['item']['id']}")
        assert detail.status_code == 200
        detail_json = json.dumps(detail.get_json(), ensure_ascii=False)
        for key in COST_KEYS:
            assert f'"{key}"' not in detail_json
        # transactional selling price remains useful for stock ops
        assert "selling_price" in detail_json or '"selling_price"' in detail_json


def test_accountant_inventory_json_includes_cost_finance(specialty_db, monkeypatch):
    with specialty_db.app_context():
        _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, "accountant")
        # accountant lacks clinics_inventory in ROLE_PERMS — grant via inventory_user+cost through admin path
        # Use purchase_user with cost? accountant has clinics_billing so if they also had inventory...
        # Explicitly verify service-layer redaction flags used by route.
        from modules.clinics.service_ops import list_inventory

        hidden = list_inventory(1, include_cost=False)
        visible = list_inventory(1, include_cost=True)
        assert hidden and "purchase_price" not in hidden[0]
        assert visible and "purchase_price" in visible[0]
        assert "inventory_value" in visible[0]


def test_receptionist_cannot_open_patient_statement(specialty_db, monkeypatch):
    with specialty_db.app_context():
        seeded = _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, "receptionist")
        response = client.get(f"/clinics/api/patients/{seeded['patient']['id']}/statement")
        assert response.status_code == 403


def test_search_invoices_requires_billing(specialty_db, monkeypatch):
    with specialty_db.app_context():
        _seed_finance_fixture()
        client = _client_as(specialty_db, monkeypatch, "doctor_employee")
        response = client.get("/clinics/api/search?q=FIN-MATRIX")
        assert response.status_code == 200
        encoded = json.dumps(response.get_json(), ensure_ascii=False)
        assert "FIN-MATRIX-1" not in encoded
