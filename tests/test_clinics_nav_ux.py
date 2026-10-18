"""Phase UX — role-aware clinics navigation matrix."""
from __future__ import annotations

from types import SimpleNamespace

from modules.clinics.service_dashboard import build_nav_matrix


def _emp(role: str, perms: set[str]):
    return SimpleNamespace(
        id=1,
        name=role,
        username=role,
        profile_pic="",
        role=role if role == "admin" else "employee",
        is_active=True,
        has_permission=lambda key, _p=perms: key in _p,
        roles=[SimpleNamespace(permissions=[SimpleNamespace(name=k) for k in perms])],
    )


def test_owner_nav_groups_and_hides_inventory_subpages():
    nav = build_nav_matrix(
        _emp("admin", set()),
        {"organization_mode": "medical_center"},
        current_doctor_id=None,
    )
    assert nav["persona"] == "owner"
    assert nav["items"]["dashboard"] is True
    assert nav["items"]["activity"] is True
    assert nav["items"]["reception"] is True
    assert nav["items"]["inventory"] is True
    assert nav["items"]["purchases"] is True
    assert nav["items"]["inventory_movements"] is False
    assert nav["items"]["inventory_batches"] is False
    assert nav["items"]["settings"] is True
    assert "الإدارة" in nav["groups_default_collapsed"]
    assert len(nav["mobile"]) <= 4


def test_doctor_nav_hides_admin_and_inventory():
    perms = {
        "clinics_dashboard",
        "clinics_patients",
        "clinics_visits",
        "clinics_clinical",
        "clinics_appointments",
        "clinics_billing",
        "clinics_inventory",
        "clinics_settings",
        "clinics_reception",
    }
    nav = build_nav_matrix(
        _emp("employee", perms),
        {"organization_mode": "multi_doctor_clinic"},
        current_doctor_id=42,
    )
    assert nav["persona"] == "doctor"
    assert nav["items"]["visits"] is True
    assert nav["items"]["activity"] is False
    assert nav["items"]["patients"] is True
    assert nav["items"]["clinical"] is True
    assert nav["items"]["reception"] is False
    assert nav["items"]["inventory"] is False
    assert nav["items"]["purchases"] is False
    assert nav["items"]["doctors"] is False
    assert nav["items"]["settings"] is False
    assert nav["items"]["cash"] is False
    assert "visits" in nav["mobile"] or "patients" in nav["mobile"]
    assert nav["topbar"]["reception"] is False


def test_reception_nav_ops_focused():
    perms = {
        "clinics_dashboard",
        "clinics_reception",
        "clinics_appointments",
        "clinics_patients",
        "clinics_billing",
        "clinics_clinical",
        "clinics_inventory",
    }
    nav = build_nav_matrix(
        _emp("employee", perms),
        {"organization_mode": "solo_clinic"},
        current_doctor_id=None,
    )
    assert nav["persona"] == "reception"
    assert nav["items"]["reception"] is True
    assert nav["items"]["activity"] is False
    assert nav["items"]["patients"] is True
    assert nav["items"]["billing"] is True
    assert nav["items"]["clinical"] is False
    assert nav["items"]["inventory"] is False
    assert nav["items"]["doctors"] is False
    assert nav["items"]["rooms"] is False
    assert nav["items"]["settlements"] is False
    assert len(nav["mobile"]) <= 4


def test_solo_clinic_hides_rooms_for_non_owner():
    perms = {"clinics_reception", "clinics_billing", "clinics_dashboard", "clinics_admin"}
    # clinics_admin alone still marks owner; use reception without admin:
    perms = {"clinics_reception", "clinics_billing", "clinics_dashboard", "clinics_patients"}
    nav = build_nav_matrix(
        _emp("employee", perms),
        {"organization_mode": "solo_clinic"},
        current_doctor_id=None,
    )
    assert nav["persona"] == "reception"
    assert nav["items"]["rooms"] is False
    assert nav["items"]["settlements"] is False


def test_linked_doctor_with_admin_perm_stays_doctor_focused():
    """Linked clinic doctors keep a clinical nav even if granted clinics_admin."""
    perms = {"clinics_admin", "clinics_clinical", "clinics_visits", "clinics_patients", "clinics_inventory"}
    nav = build_nav_matrix(
        _emp("employee", perms),
        {"organization_mode": "medical_center"},
        current_doctor_id=7,
    )
    assert nav["persona"] == "doctor"
    assert nav["items"]["inventory"] is False
    assert nav["items"]["clinical"] is True


def test_workspace_sidebar_has_nav_keys_and_no_movements_link():
    from pathlib import Path

    html = Path("templates/clinics/workspace.html").read_text(encoding="utf-8")
    assert 'data-nav-key="dashboard"' in html
    assert 'data-nav-key="activity"' in html
    assert 'data-nav-key="inventory"' in html
    assert "inventory/movements" not in html
    assert "inventory/batches" not in html
    assert "nav.js" in html
    assert 'data-nav-group="more"' in html
    assert "مخطط الأسنان" not in html
    assert "طب الأطفال" not in html or 'data-nav-key' not in html.split("طب الأطفال")[0][-80:]


def test_patient_profile_uses_hub_tabs():
    from pathlib import Path

    js = Path("static/clinics/patient-profile.js").read_text(encoding="utf-8")
    assert "buildHubs" in js
    assert "data-profile-hub" in js
    assert "السجل السريري" in js
    assert "cx-subtabs" in js
