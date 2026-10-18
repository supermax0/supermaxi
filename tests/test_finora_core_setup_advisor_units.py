"""Actual separate company databases: reviewed recommendations, limits and stale consultations."""
import pytest

from tests.test_finora_core_accounts import accounts, env, link, propose, approve, state  # noqa: F401


@pytest.mark.parametrize("text,key,expected", [("ماعندي تقسيط", "installments", False), ("بدون صيانة", "maintenance", False), ("ماعدي توصيل", "delivery", False), ("ما احتاج التقسيط", "installments", False), ("ما عندي بيع بالتقسيط", "installments", False), ("لا صيانة", "maintenance", False), ("عندي صيانة", "maintenance", True), ("نعم", "maintenance", True), ("لا", "delivery", False)])
def test_customer_answers_keep_explicit_negations(text, key, expected):
    from modules.finora_core.brain.setup_advisor import _answers
    from modules.finora_core.brain.extract import normalize
    assert _answers(normalize(text), {}, key)[key] is expected


def turn(ctx, text, *, ref=None, customer_ref=None):
    from modules.finora_core.store import core_session
    from modules.finora_core.brain.models import FcCustomer, FcConversationCustomer
    from modules.finora_core.brain.setup_advisor import consult
    from modules.finora_core.brain.tenant_setup import inspect_account
    cid = str(ref or ctx[3]["c1"])
    with ctx[0].app_context(), core_session() as s:
        binding = s.get(FcConversationCustomer, str(customer_ref or ctx[3]["c1"]))
        customer = s.get(FcCustomer, binding.customer_id)
        result = consult(s, customer, cid, text, activity="محل اجهزه كهربائيه" if "تنصح" in text else None,
                         state=inspect_account(s, customer))
        s.commit()
        return result


def prepare(ctx, sales="مفرد"):
    assert "مفرد، جملة" in turn(ctx, "شنو تنصحني لمحل أجهزة كهربائية؟")["reply"]
    assert "تقسيط" in turn(ctx, sales)["reply"]
    assert "صيانة" in turn(ctx, "نعم")["reply"]
    assert "توصيل" in turn(ctx, "نعم")["reply"]
    result = turn(ctx, "لا")
    assert "المخزون" in result["reply"] and "الأقساط" in result["reply"] and "الصيانة" in result["reply"]
    assert result["action"] is None
    return result


@pytest.mark.parametrize("sales,business_type", [("مفرد", "general"), ("جملة", "wholesale")])
def test_advice_is_reviewed_and_changes_only_the_bound_company(accounts, sales, business_type):
    link(accounts)
    link(accounts, "c2", "client-b")
    before_a, before_b = state(accounts, "client-a"), state(accounts, "client-b")
    prepare(accounts, sales)
    assert turn(accounts, "شلون اضيف منتجات؟") is None
    assert state(accounts, "client-a") == before_a
    result = turn(accounts, "جهز حسابي بهذا الاقتراح")
    assert result["action"]["operation"] == "advisory"
    response = propose(accounts, operation="advisory")
    assert response.status_code == 201, response.get_json()
    approval = response.get_json()["approval"]
    assert approval["preview"]["accountScope"]["tenantSlug"] == "client-a"
    assert any("لأنك تقدم صيانة" in row["label"] for row in approval["preview"]["changes"])
    assert state(accounts, "client-a") == before_a
    assert approve(accounts, approval).status_code == 200
    own = state(accounts, "client-a")
    flags = {row["key"]: row["enabled"] for row in own["features"]}
    assert flags["maintenance"] and flags["installments"]
    assert flags["quick_sale"] is (sales == "مفرد")
    if sales == "جملة":
        assert flags["wholesale"]
    assert not flags["shipping"] and not flags["clinics"] and not flags["hr"]
    assert own["employees"] == before_a["employees"]
    assert own["businessType"] == own["coreBusinessType"] == business_type
    assert state(accounts, "client-b") == before_b


def test_advice_refuses_another_customers_conversation_and_stale_answers(accounts):
    from modules.finora_core.brain.tools import ToolError
    link(accounts)
    link(accounts, "c2", "client-b")
    with pytest.raises(ToolError, match="محادثة العميل نفسه"):
        turn(accounts, "انصحني", ref=accounts[3]["c2"])
    prepare(accounts)
    approval = propose(accounts, operation="advisory").get_json()["approval"]
    before = state(accounts, "client-a")
    turn(accounts, "بدون تقسيط")
    response = approve(accounts, approval)
    assert response.status_code != 200
    assert state(accounts, "client-a") == before


def test_recommendations_respect_plan_parents_and_do_not_invent_pages(accounts):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from modules.finora_core.brain.setup_advisor import recommendation
    from modules.finora_core.brain.models import FcCustomer, FcConversationCustomer
    from modules.finora_core.store import core_session
    from modules.finora_core.brain.tenant_setup import inspect_account, PROTECTED
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    link(accounts)
    with accounts[0].app_context():
        row = SubscriptionPlan.query.filter_by(plan_key="basic").one()
        features = row.get_features()
        features["installments"] = False
        row.set_features(features)
        db.session.commit()
    result = prepare(accounts)
    assert "خارج الباقة" in result["reply"]
    with accounts[0].app_context(), core_session() as s:
        binding = s.get(FcConversationCustomer, str(accounts[3]["c1"]))
        customer = s.get(FcCustomer, binding.customer_id)
        info = recommendation(s, customer, str(accounts[3]["c1"]), inspect_account(s, customer))
        assert set(info["updates"]) <= set(TENANT_FEATURE_LABELS)
        assert not set(info["updates"]) & PROTECTED
        assert all(not enabled for key, enabled in info["updates"].items() if key.startswith("installments"))
        assert info["unavailable"]
    approval = propose(accounts, operation="advisory").get_json()["approval"]
    assert approval["preview"]["unavailableFeatures"]
    assert approve(accounts, approval).status_code == 200
