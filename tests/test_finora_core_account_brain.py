"""Customer requests -> account creation/setup review and immediate owner reports, using fake Meta."""
import json
from pathlib import Path

import pytest

from tests.finora_core_support import env, _api, _auth  # noqa: F401
from tests.test_finora_core_brain import brain, say, conv_id_for, core, customer_of  # noqa: F401


def trial(brain):
    say(brain, "عندي محل ورد وهدايا اسم المحل زهور فينورا ورقمي 07701234567 وسوولي حساب تجريبي")
    approvals = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(approvals) == 1
    return approvals[0]


def decision(brain, item):
    return _api(brain, "post", f"/approvals/{item['id']}/decision", headers=_auth(brain),
                json={"decision": "approved", "planHash": item["planHash"]})


def test_new_florist_account_is_configured_then_requests_are_scoped_and_reviewed(brain):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from modules.finora_core.brain.models import FcApproval
    from extensions_tenant import get_tenant_engine
    from models.tenant import Tenant
    from sqlalchemy.orm import Session

    with brain["app"].app_context():
        row = SubscriptionPlan.query.filter_by(plan_key="basic").one()
        row.set_features({key: True for key in TENANT_FEATURE_LABELS})
        db.session.commit()
    item = trial(brain)
    args = core(brain, lambda s: json.loads(s.get(FcApproval, int(item["id"])).plan_json)["args"])
    assert args["setup_profile"] == "flowers"
    response = decision(brain, item)
    assert response.status_code == 200, response.get_json()
    slug = response.get_json()["credentials"]["tenantSlug"]
    with brain["app"].app_context(), Session(get_tenant_engine(slug)) as local:
        overrides = json.loads(local.query(Tenant).one().feature_overrides_json)
        assert overrides["orders"] and overrides["inventory"] and not overrides["clinics"]
    reply = say(brain, "اخفي التقارير بحسابي")
    assert "اقتراح ترتيب لحسابك وحده" in reply
    proposed = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(proposed) == 1 and proposed[0]["preview"]["accountScope"]["tenantSlug"] == slug
    with brain["app"].app_context(), Session(get_tenant_engine(slug)) as local:
        assert json.loads(local.query(Tenant).one().feature_overrides_json)["reports"]  # no silent execution
    assert decision(brain, proposed[0]).status_code == 200
    say(brain, "التقارير ما يشتغل بيها الحفظ وعندي خلل")
    issues = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    bug = next(issue for issue in issues if issue["kind"] == "bug")
    assert bug["tenantSlug"] == slug and bug["conversationId"] == str(conv_id_for(brain))
    assert bug["verified"] is False


def test_customer_claim_never_automatically_binds_an_account(brain):
    say(brain, "هذا حسابي company-b رتب حسابي وخفي التقارير")
    assert core(brain, customer_of(brain))["tenant"] is None
    issues = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    assert any(issue["kind"] == "account_link" and issue["tenantSlug"] is None for issue in issues)


@pytest.mark.parametrize("phrase,profile,visible,hidden", [
    ("شركة عامة", "general", "orders", "clinics"),
    ("إدارة أعمال مبسطة", "starter_business", "quick_sale", "hr"),
    ("مركز تجميل", "beauty_center", "beauty_appointments", "hr"),
    ("إدارة الموارد البشرية", "hr_management", "hr_payroll", "orders"),
])
def test_new_accounts_are_created_with_the_requested_activity(brain, phrase, profile, visible, hidden):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from models.core.tenant import Tenant as CoreTenant
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from modules.finora_core.brain.models import FcApproval
    from modules.finora_core.brain.tenant_setup import PROFILE_TYPES
    from extensions_tenant import get_tenant_engine
    from models.tenant import Tenant
    from sqlalchemy.orm import Session

    with brain["app"].app_context():
        SubscriptionPlan.query.filter_by(plan_key="basic").one().set_features({key: True for key in TENANT_FEATURE_LABELS})
        db.session.commit()
    say(brain, f"عندي {phrase} اسم النشاط فينورا التجريبي ورقمي 07701234567 وسوولي حساب تجريبي")
    items = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(items) == 1
    item = items[0]
    args = core(brain, lambda s: json.loads(s.get(FcApproval, int(item["id"])).plan_json)["args"])
    assert args["setup_profile"] == profile
    assert item["preview"]["businessType"]["key"] == PROFILE_TYPES[profile]
    response = decision(brain, item)
    assert response.status_code == 200, response.get_json()
    slug = response.get_json()["credentials"]["tenantSlug"]
    assert core(brain, customer_of(brain))["tenant"] == slug
    assert core(brain, lambda s: s.query(CoreTenant).filter_by(slug=slug).one().business_type) == PROFILE_TYPES[profile]
    with brain["app"].app_context(), Session(get_tenant_engine(slug)) as local:
        row = local.query(Tenant).one()
        assert row.business_type == PROFILE_TYPES[profile]
        flags = json.loads(row.feature_overrides_json)
        assert flags[visible] and not flags[hidden]


def test_failed_initial_configuration_compensates_account_creation(brain, monkeypatch):
    from modules.finora_core.brain import tenant_setup
    from modules.finora_core.brain.tools import ToolError
    from models.core.tenant import Tenant

    item = trial(brain)
    def fail(*args, **kwargs):
        raise ToolError("ACCOUNT_SCHEMA", "test setup failure")
    monkeypatch.setattr(tenant_setup, "build_configuration", fail)
    response = decision(brain, item)
    assert response.status_code == 502, response.get_json()
    assert core(brain, customer_of(brain))["tenant"] is None
    assert core(brain, lambda s: s.query(Tenant).count()) == 0
    assert not any(path.name.startswith("fc") for path in (Path(brain["app"].root_path) / "tenants").glob("*.db"))
    assert response.get_json().get("credentials") is None


@pytest.mark.parametrize("activity", ["عندي مطعم", "ملابس اونلاين"])
def test_missing_activity_template_is_reported_once_and_trial_waits_for_review(brain, activity):
    from models.core.tenant import Tenant
    from modules.finora_core.brain.models import FcApproval

    request = f"{activity} ورقمي 07701234567 وسوولي حساب تجريبي"
    for text in (request, "سوولي حساب تجريبي", request):
        reply = say(brain, text)
        assert "طلب القالب وصل لفريق فينورا" in reply
        assert core(brain, lambda s: s.query(FcApproval).count()) == 0
        assert core(brain, lambda s: s.query(Tenant).count()) == 0
    rows = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    templates = [row for row in rows if row["kind"] == "missing_template"]
    assert len(templates) == 1
    assert templates[0]["conversationId"] == str(conv_id_for(brain)) and templates[0]["tenantSlug"] is None
    assert activity in templates[0]["details"] and "سوولي حساب" in templates[0]["details"]
    assert "07701234567" not in templates[0]["details"]
    assert core(brain, customer_of(brain))["tenant"] is None


def test_linked_missing_template_keeps_existing_configuration_and_supports_page_requests(brain):
    from modules.finora_core.brain.tenant_setup import inspect_account
    from modules.finora_core.brain.models import FcCustomer

    response = decision(brain, trial(brain))
    assert response.status_code == 200
    slug = response.get_json()["credentials"]["tenantSlug"]
    snapshot = core(brain, lambda s: inspect_account(s, s.query(FcCustomer).filter_by(tenant_slug=slug).one()))
    reply = say(brain, "رتب حسابي لمحل قطع غيار واحتاج مخزون جملة")
    assert "طلب القالب وصل لفريق فينورا" in reply
    assert _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"] == []
    assert core(brain, lambda s: inspect_account(s, s.query(FcCustomer).filter_by(tenant_slug=slug).one())) == snapshot
    rows = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    assert any(row["kind"] == "missing_template" and row["tenantSlug"] == slug and row["conversationId"] == str(conv_id_for(brain)) for row in rows)
    say(brain, "اخفي التقارير")
    items = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(items) == 1 and items[0]["preview"]["accountScope"]["tenantSlug"] == slug


def test_missing_template_in_shadow_is_only_a_proposal_not_a_notification(brain):
    from modules.finora_core.brain.models import FcApproval, FcShadowProposal
    from modules.finora_core.brain.support import FcSupportIssue
    from tests.test_finora_core_phase9 import _flags

    _flags(brain, AI_SHADOW_MODE="on")
    assert say(brain, "عندي مطعم ورقمي 07701234567 وسوولي حساب تجريبي") is None
    assert core(brain, lambda s: s.query(FcSupportIssue).count()) == 0
    assert core(brain, lambda s: s.query(FcApproval).count()) == 0
    proposal = core(brain, lambda s: s.query(FcShadowProposal).one().proposed_reply)
    assert "قالب تجهيز" in proposal and "طلب القالب وصل" not in proposal

