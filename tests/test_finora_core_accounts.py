"""Real, isolated company databases: linking, reviewed setup, permissions and owner reports."""
import json

import pytest
from sqlalchemy.orm import Session

from tests.test_finora_core_api import env, _auth, _seed_house, HOUSE  # noqa: F401

BASE = "/api/v1/finora-core"


@pytest.fixture
def accounts(env, monkeypatch):
    from extensions import db
    from extensions_tenant import get_tenant_engine
    from models.core.tenant import Tenant
    from models.core.subscription_plan import SubscriptionPlan
    from models.tenant import Tenant as LocalTenant
    from models.employee import Employee
    from models.role import Role, Permission, employee_roles, role_permissions
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from modules.finora_core import api

    monkeypatch.setattr(api, "_notify_customer", lambda *args: None)
    ids = _seed_house(env)
    with env.app_context():
        Tenant.__table__.create(db.engine, checkfirst=True)
        SubscriptionPlan.__table__.create(db.engine, checkfirst=True)
        with Session(db.engine) as s:
            plan = SubscriptionPlan(plan_key="basic", name="Test", features_json=json.dumps({key: True for key in TENANT_FEATURE_LABELS}))
            s.add(plan)
            for slug in ("client-a", "client-b"):
                s.add(Tenant(slug=slug, name=slug, is_active=True, db_path=f"tenants/{slug}.db"))
                engine = get_tenant_engine(slug)
                db.Model.metadata.create_all(engine)
                with Session(engine) as local:
                    local.add(LocalTenant(id=1, name=slug, business_type="starter_business", plan_key="basic"))
                    local.add(Employee(id=1, name="Owner", username="admin", password="private-hash", role="admin", tenant_id=1))
                    local.add(Employee(id=2, name="سارة", username="sara", password="private-hash", role="cashier", tenant_id=1))
                    local.add(Role(id=1, name="استقبال", permissions=[Permission(name="clinics_reception")]))
                    local.add(Role(id=2, name="Administrator", permissions=[Permission(name="manage_users")]))
                    if slug == "client-b":
                        local.add(Role(id=99, name="Only company B"))
                    local.commit()
            s.commit()
    client = env.test_client()
    headers, _ = _auth(client)
    return env, client, headers, ids


def link(ctx, cid="c1", slug="client-a"):
    _, client, headers, ids = ctx
    res = client.post(f"{BASE}/conversations/{ids[cid]}/account/link", headers=headers,
                      json={"tenantSlug": slug, "ownershipVerified": True, "reason": "تحقق المالك عبر قناة الشركة المسجلة"})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def propose(ctx, **data):
    _, client, headers, ids = ctx
    return client.post(f"{BASE}/conversations/{ids['c1']}/account/propose", headers=headers, json=data)


def approve(ctx, approval):
    return ctx[1].post(f"{BASE}/approvals/{approval['id']}/decision", headers=ctx[2],
                       json={"decision": "approved", "planHash": approval["planHash"]})


def state(ctx, slug):
    from modules.finora_core.store import core_session
    from modules.finora_core.brain.models import FcCustomer
    from modules.finora_core.brain.tenant_setup import inspect_account
    with ctx[0].app_context(), core_session() as s:
        return inspect_account(s, FcCustomer(tenant_slug=slug))


def test_link_requires_verified_identity_and_owner_access(accounts):
    _, client, headers, ids = accounts
    path = f"{BASE}/conversations/{ids['c1']}/account"
    assert client.get(path, headers=headers).get_json()["tenantSlug"] is None
    assert client.post(path + "/link", headers=headers, json={"tenantSlug": "client-a", "reason": "customer claimed"}).status_code == 400
    assert client.post(path + "/link", headers=headers, json={"tenantSlug": HOUSE, "reason": "verified ownership", "ownershipVerified": True}).status_code == 409
    linked = link(accounts)
    assert linked["linked"] and linked["account"]["tenantSlug"] == "client-a"
    wire = json.dumps(linked)
    assert "private-hash" not in wire and "client-b" not in wire and "overrides" not in linked["account"]
    assert client.post(path + "/link", headers=headers, json={"tenantSlug": "client-b", "reason": "verified ownership", "ownershipVerified": True}).status_code == 409
    assert client.post(f"{BASE}/conversations/{ids['c2']}/account/link", headers=headers, json={"tenantSlug": "client-a", "reason": "verified ownership", "ownershipVerified": True}).status_code == 409
    viewer, _ = _auth(client, "viewer")
    assert client.get(path, headers=viewer).status_code == 403
    assert client.get(f"{BASE}/support/issues", headers=viewer).status_code == 403


def test_account_catalogue_covers_every_official_business_activity(accounts):
    from routes.superadmin import BUSINESS_TYPES
    from modules.finora_core.brain.tenant_setup import PROFILES, PROFILE_TYPES
    from modules.finora_core.brain.registry import _TRIAL_PLAN

    response = accounts[1].get(f"{BASE}/conversations/{accounts[3]['c1']}/account", headers=accounts[2])
    assert response.status_code == 200
    assert {row["key"] for row in response.get_json()["profiles"]} == set(PROFILES)
    assert set(PROFILE_TYPES.values()) == set(BUSINESS_TYPES)
    assert set(_TRIAL_PLAN["properties"]["setup_profile"]["enum"]) == set(PROFILES) | {None}


def test_business_defaults_and_dedicated_modules_match_real_activity():
    from modules.finora_core.brain.tenant_setup import profile_features, PROTECTED
    from utils.starter_business import DEFAULT_FEATURES
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS, default_feature_enabled

    starter = profile_features("starter_business")
    assert {key for key, enabled in starter.items() if enabled} == DEFAULT_FEATURES - PROTECTED
    general = profile_features("general")
    assert general["quick_sale"] and general["purchases"]
    for key in ("hr", "hr_payroll", "beauty", "beauty_appointments", "clinics", "dental.view", "wholesale", "food"):
        assert not general[key]
    for key in TENANT_FEATURE_LABELS:
        if key not in PROTECTED and not key.startswith(("hr", "beauty", "clinics", "dental.", "wholesale", "food")):
            assert general[key] == default_feature_enabled(key, business_type="general")
    hr = profile_features("hr_management")
    assert {key for key, enabled in hr.items() if enabled} == {key for key in TENANT_FEATURE_LABELS if key == "hr" or key.startswith("hr_")}
    beauty = profile_features("beauty_center")
    assert all(beauty[key] for key in ("beauty", "beauty_appointments", "beauty_services", "inventory", "customers", "cash"))
    assert all(not beauty[key] for key in ("hr", "food", "clinics", "wholesale"))
    assert not set(starter) & PROTECTED


@pytest.mark.parametrize("phrase,profile,business", [
    ("شركة عامة", "general", "general"),
    ("إدارة أعمال مبسّطة", "starter_business", "starter_business"),
    ("مركز تجميل", "beauty_center", "beauty_center"),
    ("إدارة الموارد البشرية", "hr_management", "hr_management"),
    ("شؤون الموظفين", "hr_management", "hr_management"),
    ("تجارة الجملة", "wholesale", "wholesale"),
    ("مواد غذائية جملة ومفرد", "grocery", "food_wholesale_retail"),
    ("عيادة", "clinic", "clinic"),
    ("عيادة أسنان", "dental_clinic", "clinic"),
    ("محل ورد وهدايا", "flowers", "starter_business"),
])
def test_customer_activity_requests_are_recognized(phrase, profile, business):
    from modules.finora_core.brain.extract import extract
    from modules.finora_core.brain.tenant_setup import propose

    extracted = extract(f"عندي {phrase}")
    assert extracted.facts["businessType"] == business
    assert "human_request" not in extracted.intents
    proposal = propose(f"رتب حسابي لنشاط {phrase}", {})
    assert proposal["profile"] == profile and proposal["operation"] == "profile"


@pytest.mark.parametrize("text", ["اريد موظف بشري", "اريد اتكلم مع الفريق", "عندي موارد بشرية وأريد موظف حقيقي"])
def test_explicit_human_requests_still_transfer_to_the_team(text):
    from modules.finora_core.brain.extract import extract

    assert "human_request" in extract(text).intents


@pytest.mark.parametrize("text,activity", [
    ("عندي محل قطع غيار واريد حساب تجريبي", "محل قطع غيار"),
    ("عندي مطعم ورقمي 07701234567", "مطعم"),
    ("مطعم", "مطعم"),
    ("محل قطع غيار", "محل قطع غيار"),
    ("نشاطي بيع مستلزمات الحيوانات واحتاج برنامج", "بيع مستلزمات الحيوانات"),
    ("جهز حسابي لنشاط تأجير السيارات", "تاجير السيارات"),
    ("رتبلي حسابي لمحل قطع غيار واحتاج مخزون جملة", "محل قطع غيار"),
    ("لدي شركة نقل وشحن", "شركه نقل وشحن"),
    ("عندي محل مواد غذائية جملة ومفرد", None),
    ("عندي محل ورد وهدايا ورقمي 07701234567", None),
    ("نشاطي إدارة الموارد البشرية", None),
    ("رتب حسابي لنشاط شركة عامة", None),
    ("عندي عيادة أسنان", None),
    ("عندي مشكلة بحفظ المخزون", None),
    ("عندي محل", None),
    ("اخفي التقارير", None),
])
def test_missing_template_detection_is_grounded_in_customer_activity(text, activity):
    from modules.finora_core.brain.tenant_setup import missing_profile_request

    assert missing_profile_request(text) == activity


def test_unknown_manual_template_notifies_owner_without_changing_companies(accounts):
    link(accounts)
    before_a, before_b = state(accounts, "client-a"), state(accounts, "client-b")
    response = propose(accounts, operation="profile", profile="car_parts")
    assert response.status_code == 400
    rows = accounts[1].get(f"{BASE}/support/issues", headers=accounts[2]).get_json()["items"]
    issue = next(row for row in rows if row["kind"] == "missing_template")
    assert issue["title"] == "طلب قالب جديد لنشاط العميل"
    assert "car_parts" in issue["details"] and issue["tenantSlug"] == "client-a"
    assert issue["conversationId"] == str(accounts[3]["c1"]) and issue["verified"]
    assert state(accounts, "client-a") == before_a and state(accounts, "client-b") == before_b
    viewer, _ = _auth(accounts[1], "viewer")
    assert accounts[1].get(f"{BASE}/support/issues", headers=viewer).status_code == 403
    assert propose(accounts, operation="profile", profile=["car_parts"]).status_code == 400
    assert propose(accounts, operation="profile", profile={"password": "private-password"}).status_code == 400
    issues = accounts[1].get(f"{BASE}/support/issues", headers=accounts[2]).get_json()["items"]
    assert "private-password" not in json.dumps(issues)


@pytest.mark.parametrize("profile,visible,hidden", [("general", "orders", "clinics"), ("starter_business", "quick_sale", "hr"), ("beauty_center", "beauty_appointments", "hr"), ("hr_management", "hr_payroll", "orders"), ("flowers", "orders", "clinics"), ("wholesale", "wholesale", "food"), ("grocery", "food", "clinics"), ("clinic", "clinics", "dental.view"), ("dental_clinic", "dental.view", "food")])
def test_profile_review_applies_only_bound_company(accounts, profile, visible, hidden):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    link(accounts)
    link(accounts, "c2", "client-b")
    before_a, before_b = state(accounts, "client-a"), state(accounts, "client-b")
    res = propose(accounts, operation="profile", profile=profile)
    assert res.status_code == 201, res.get_json()
    approval = res.get_json()["approval"]
    assert approval["preview"]["accountScope"]["tenantSlug"] == "client-a"
    assert state(accounts, "client-a") == before_a
    done = approve(accounts, approval)
    assert done.status_code == 200, done.get_json()
    after = {row["key"]: row for row in state(accounts, "client-a")["features"]}
    assert after[visible]["enabled"] and not after[hidden]["enabled"]
    from modules.finora_core.brain.tenant_setup import PROFILE_TYPES
    own = state(accounts, "client-a")
    assert own["businessType"] == own["coreBusinessType"] == PROFILE_TYPES[profile]
    assert state(accounts, "client-b") == before_b
    if profile in {"clinic", "dental_clinic", "wholesale"}:
        from flask import g
        with accounts[0].test_request_context():
            g.tenant = "client-a"
            if profile == "wholesale":
                from modules.wholesale.guards import is_wholesale_tenant
                assert is_wholesale_tenant()
            else:
                from modules.clinics.guards import is_clinics_tenant
                assert is_clinics_tenant()
    assert approve(accounts, approval).status_code == 409
    with accounts[0].app_context(), Session(db.engine) as s:
        assert all(s.query(SubscriptionPlan).one().get_features().values())


def test_permissions_are_local_reviewed_and_owner_protected(accounts):
    link(accounts)
    before_b = state(accounts, "client-b")
    assert approve(accounts, propose(accounts, operation="profile", profile="clinic").get_json()["approval"]).status_code == 200
    assert propose(accounts, operation="permissions", employee_id=1, permission_preset="sales").status_code == 400
    assert propose(accounts, operation="permissions", employee_id=2, permission_preset="sales", role_ids=[99]).status_code == 400
    assert propose(accounts, operation="permissions", employee_id=2, permission_preset="sales", role_ids=[2]).status_code == 400
    assert propose(accounts, operation="permissions", employee_id=True, permission_preset="sales").status_code == 400
    res = propose(accounts, operation="permissions", employee_id=2, permission_preset="reception", role_ids=[1])
    approval = res.get_json()["approval"]
    assert approval["preview"]["employeeName"] == "سارة"
    assert approval["preview"]["roleChanges"]["after"] == ["استقبال"]
    viewer, _ = _auth(accounts[1], "viewer")
    assert accounts[1].get(f"{BASE}/approvals", headers=viewer).get_json()["items"] == []
    assert approve(accounts, approval).status_code == 200
    employee = state(accounts, "client-a")["employees"][1]
    assert employee["permissions"]["can_manage_customers"] and not employee["permissions"]["can_see_financial"]
    assert employee["roleIds"] == [1]
    from flask import g, session
    from modules.clinics.guards import can_use_clinics
    with accounts[0].test_request_context():
        g.tenant = "client-a"
        session["user_id"] = 2
        assert can_use_clinics("clinics_reception")
    assert state(accounts, "client-b") == before_b


def test_tampered_target_stale_state_and_direct_execution_are_refused(accounts):
    from extensions_tenant import get_tenant_engine
    from models.tenant import Tenant
    from modules.finora_core.brain.tools import ToolError, run_tool
    from modules.finora_core.brain.models import FcCustomer
    from modules.finora_core.brain.tenant_setup import build_configuration, apply_configuration
    from modules.finora_core.store import core_session
    linked = link(accounts)
    assert propose(accounts, operation="profile", profile="flowers", tenantSlug="client-b").status_code == 400
    with accounts[0].app_context(), core_session() as s:
        customer = s.get(FcCustomer, int(linked["customerId"]))
        args = build_configuration(s, customer, {"operation": "profile", "profile": "flowers"})
        with pytest.raises(ToolError):
            run_tool(s, "configure_tenant", args, customer=customer, actor="AI", actor_type="ai")
        with pytest.raises(ToolError):
            apply_configuration(s, customer, {**args, "tenant_slug": "client-b"})
        with pytest.raises(ToolError):
            apply_configuration(s, customer, {**args, "feature_updates": {"dashboard": False}})
    approval = propose(accounts, operation="feature", feature="orders", enabled=False).get_json()["approval"]
    with accounts[0].app_context(), Session(get_tenant_engine("client-a")) as local:
        local.query(Tenant).one().feature_overrides_json = '{"expenses": false}'
        local.commit()
    failed = approve(accounts, approval)
    assert failed.status_code == 409, failed.get_json()
    assert "orders" not in state(accounts, "client-a")["overrides"]


def test_unavailable_features_report_privately_and_never_change_plan(accounts):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    link(accounts)
    with accounts[0].app_context(), Session(db.engine) as s:
        plan = s.query(SubscriptionPlan).one()
        flags = plan.get_features()
        flags["inventory"] = False
        plan.set_features(flags)
        s.commit()
    for _ in range(2):
        assert propose(accounts, operation="feature", feature="inventory", enabled=True).status_code == 400
    assert propose(accounts, operation="feature", feature="invented-page", enabled=True).status_code == 400
    _, client, headers, ids = accounts
    rows = client.get(f"{BASE}/support/issues", headers=headers).get_json()["items"]
    assert len(rows) == 2 and all(row["tenantSlug"] == "client-a" and row["conversationId"] == str(ids["c1"]) for row in rows)
    assert not any(row["verified"] for row in rows)
    assert not state(accounts, "client-a")["features"][next(i for i, r in enumerate(state(accounts, "client-a")["features"]) if r["key"] == "inventory")]["enabled"]
    assert client.post(f"{BASE}/support/issues/{rows[0]['id']}/resolve", headers=headers).status_code == 200
    assert len(client.get(f"{BASE}/support/issues", headers=headers).get_json()["items"]) == 1


def test_text_proposals_require_unambiguous_actual_staff_and_features():
    from modules.finora_core.brain.tenant_setup import propose as from_text
    state = {"employees": [{"id": 1, "name": "سارة", "username": "sara", "owner": False, "active": True}, {"id": 2, "name": "سارة", "username": "sara2", "owner": False, "active": True}]}
    assert from_text("رتب حساب عيادة اسنان", state)["profile"] == "dental_clinic"
    assert from_text("رتب حساب بياع الورد", state)["profile"] == "flowers"
    assert from_text("اخفي التقارير", state)["enabled"] is False
    assert from_text("صلاحيات سارة مبيعات", state) is None
    assert from_text("اخفي الصندوق والتقارير", state) is None
    assert from_text("اخفي التقارير", {**state, "businessType": "clinics"})["feature"] == "clinics_reports"


def test_failed_company_write_rolls_back_business_metadata_and_reports_owner(accounts, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    link(accounts)
    before_a, before_b = state(accounts, "client-a"), state(accounts, "client-b")
    approval = propose(accounts, operation="profile", profile="wholesale").get_json()["approval"]
    original = Session.commit
    def fail_company_write(local):
        if str(local.get_bind().url.database).endswith("client-a.db"):
            raise SQLAlchemyError("simulated local commit failure")
        return original(local)
    monkeypatch.setattr(Session, "commit", fail_company_write)
    response = approve(accounts, approval)
    assert response.status_code == 502, response.get_json()
    assert state(accounts, "client-a") == before_a
    assert state(accounts, "client-b") == before_b
    rows = accounts[1].get(f"{BASE}/support/issues", headers=accounts[2]).get_json()["items"]
    assert any(row["kind"] == "configuration_error" and row["verified"] for row in rows)


def test_specialist_page_requires_real_activity_not_just_a_visibility_flag(accounts):
    link(accounts)
    assert propose(accounts, operation="feature", feature="wholesale_sales", enabled=True).status_code == 400
    assert propose(accounts, operation="feature", feature="clinics_appointments", enabled=True).status_code == 400

