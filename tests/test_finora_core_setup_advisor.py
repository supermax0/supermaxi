"""Instagram customer -> persistent consultation -> reviewed, isolated provisioning (fake Meta only)."""
import json

from tests.finora_core_support import env, _api, _auth  # noqa: F401
from tests.test_finora_core_brain import brain, say, core, conv_id_for  # noqa: F401
from tests.test_finora_core_account_brain import decision


def prepare(brain, platform="instagram"):
    from tests.finora_core_support import IG_ID
    kwargs = {"platform": "instagram", "account": IG_ID} if platform == "instagram" else {}
    assert "مفرد، جملة" in say(brain, "عندي محل أجهزة كهربائية شنو الميزات الي احتاجها ممكن تنصحني؟", **kwargs)
    assert "تقسيط" in say(brain, "مفرد", **kwargs)
    assert "صيانة" in say(brain, "نعم", **kwargs)
    assert "توصيل" in say(brain, "نعم", **kwargs)
    reply = say(brain, "لا", **kwargs)
    assert "المخزون" in reply and "الأقساط" in reply and "الصيانة" in reply
    assert "بعد مراجعة المشرف" in reply
    assert _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"] == []
    return kwargs


def test_instagram_custom_business_consultation_and_reviewed_trial(brain):
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from models.core.tenant import Tenant as CoreTenant
    from models.tenant import Tenant
    from extensions_tenant import get_tenant_engine
    from sqlalchemy.orm import Session
    with brain["app"].app_context():
        SubscriptionPlan.query.filter_by(plan_key="basic").one().set_features({key: True for key in TENANT_FEATURE_LABELS})
        db.session.commit()
    kwargs = prepare(brain)
    assert core(brain, lambda s: s.query(CoreTenant).count()) == 0
    reply = say(brain, "سوولي حساب تجريبي بهذا الاقتراح اسم المحل نور للأجهزة ورقمي 07701234567", **kwargs)
    assert "مشرف فينورا" in reply
    items = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(items) == 1 and items[0]["preview"]["businessType"]["key"] == "general"
    assert any("لأنك تقدم صيانة" in row["label"] for row in items[0]["preview"]["tenantActions"])
    assert core(brain, lambda s: s.query(CoreTenant).count()) == 0
    response = decision(brain, items[0])
    assert response.status_code == 200, response.get_json()
    slug = response.get_json()["credentials"]["tenantSlug"]
    with brain["app"].app_context(), Session(get_tenant_engine(slug)) as local:
        tenant = local.query(Tenant).one()
        flags = json.loads(tenant.feature_overrides_json)
        assert flags["maintenance"] and flags["installments"] and flags["inventory"]
        assert not flags["shipping"] and not flags["clinics"]
    issues = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    assert any(row["kind"] == "missing_template" and row["conversationId"] == str(conv_id_for(brain)) for row in issues)


def test_consultation_remembers_activity_answer_and_does_not_swallow_support(brain):
    from modules.finora_core.brain.models import FcApproval
    assert "نوع نشاطك" in say(brain, "شنو الصفحات الي احتاجها تنصحني؟")
    assert "مفرد، جملة" in say(brain, "أجهزة كهربائية")
    assert "تقسيط" in say(brain, "مفرد")
    say(brain, "عندي خلل النظام مايحفظ")
    issues = _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"]
    assert any(row["kind"] == "bug" for row in issues)
    assert core(brain, lambda s: s.query(FcApproval).count()) == 0


def test_consultation_does_not_claim_a_blocked_or_incomplete_trial_was_submitted(brain):
    from tests.test_finora_core_phase9 import _flags
    kwargs = prepare(brain)
    reply = say(brain, "لا تجهز حسابي هسه", **kwargs)
    assert "جاهز لمراجعة" not in reply
    reply = say(brain, "سوولي حساب تجريبي بهذا الاقتراح", **kwargs)
    assert "اسم العيادة" in reply
    assert "رقم هاتفك" in say(brain, "اسم المحل نور للأجهزة", **kwargs)
    assert _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"] == []
    _flags(brain, AI_ACCOUNT_CREATION="off")
    reply = say(brain, "سوولي حساب تجريبي ورقمي 07701234567", **kwargs)
    assert "متوقف" in reply
    assert _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"] == []


def test_shadow_consultation_previews_custom_setup_without_sends_or_notifications(brain):
    from tests.test_finora_core_phase9 import _flags, _proposals
    from models.core.tenant import Tenant
    _flags(brain, AI_SHADOW_MODE="on")
    sends_before = len(brain["graph"].sends())
    for text in ("عندي محل أجهزة كهربائية شنو الميزات الي احتاجها تنصحني؟", "مفرد", "نعم", "نعم", "لا",
                 "سوولي حساب تجريبي اسم المحل نور للأجهزة ورقمي 07701234567"):
        assert say(brain, text) is None
    latest = _proposals(brain)["items"][0]
    assert any(row["kind"] == "start_trial" and "تجهيز مخصص" in str(row["preview"]) for row in latest["approvals"]), latest["actions"]
    assert len(brain["graph"].sends()) == sends_before
    assert _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"] == []
    assert _api(brain, "get", "/support/issues", headers=_auth(brain)).get_json()["items"] == []
    assert core(brain, lambda s: s.query(Tenant).count()) == 0
