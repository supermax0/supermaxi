"""Regression of the real dental-clinic dialogue and scoped account intake."""
import pytest

from tests.finora_core_support import env, _api, _auth  # noqa: F401
from tests.test_finora_core_brain import brain, core, customer_of, conv_id_for  # noqa: F401
from tests.test_finora_core_brain import say


@pytest.mark.parametrize("text", ["سويلي حساب", "سويلي حساب ودزه", "سوي حساب", "انشاء حساب تجريبي", "جهز حسابي"])
def test_iraqi_explicit_account_request_is_recognized(text):
    from modules.finora_core.brain.extract import extract
    assert "account_creation" in extract(text).intents


def test_receptionist_count_does_not_take_the_doctors_number():
    from modules.finora_core.brain.extract import extract
    facts = extract("موضف استقبال\n3 اطباء لكل منهم غرفه").facts
    assert facts["employees"] == 1 and facts["doctors"] == 3
    assert extract("موظفين استقبال 2 وعدنا 3 اطباء").facts["employees"] == 2


def test_literal_city_and_business_name_answers_are_grounded():
    from modules.finora_core.brain.extract import extract
    assert extract("بغداد").facts["city"] == "بغداد"
    assert extract("العراق بغداد").facts == {"country": "العراق", "city": "بغداد"}
    assert extract("الدولة العراق").facts["country"] == "العراق"
    assert extract("عيادة النور", waiting="businessName").facts["businessName"] == "عيادة النور"
    assert extract("اسم العيادة النور ورقمي 07701234567").facts["businessName"] == "النور"
    assert "businessType" not in extract("سوولي حساب بهذا الاقتراح اسم المحل نور للأجهزة ورقمي 07701234567").facts
    assert "city" not in extract("هل عندكم عملاء في بغداد؟").facts
    assert "businessName" not in extract("ليش ما طلبت اسم العيادة؟", waiting="businessName").facts
    assert "businessName" not in extract("07701234567", waiting="businessName").facts
    assert "businessName" not in extract("owner@example.com", waiting="businessName").facts
    assert "account_creation" not in extract("لا تسويلي حساب").intents


def test_real_dental_dialogue_remembers_details_and_resumes_account_after_phone(brain):
    from modules.finora_core.brain import memory
    from modules.finora_core.brain.models import FcCustomer, FcApproval, FcConversationCustomer
    from models.core.tenant import Tenant
    from tests.test_finora_core_account_brain import decision
    from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
    from models.core.subscription_plan import SubscriptionPlan
    from extensions import db
    with brain["app"].app_context():
        SubscriptionPlan.query.filter_by(plan_key="basic").one().set_features({key: True for key in TENANT_FEATURE_LABELS})
        db.session.commit()
    say(brain, "مرحبا")
    say(brain, "عيادة اسنان")
    say(brain, "3 اطباء")
    say(brain, "موضف استقبال\n3 اطباء لكل منهم غرفه")
    say(brain, "فرع واحد")
    reply = say(brain, "بغداد")
    assert "أتأكد" not in reply and "مدينة" not in reply
    advice = say(brain, "انصحني شنو احتاج العيادة الاسنان")
    assert "مخطط الأسنان" in advice and "موظف الاستقبال" in advice and "الفواتير" in advice
    assert "اسم العيادة" in say(brain, "سويلي حساب")
    assert "رقم هاتفك" in say(brain, "عيادة النور")
    # Another customer cannot complete the first customer's request.
    say(brain, "07701234567", sender="cust-other")
    assert core(brain, lambda s: s.query(FcApproval).count()) == 0
    reply = say(brain, "07701234567")
    assert "مدينة" not in reply and "أتأكد" not in reply
    items = _api(brain, "get", "/approvals", headers=_auth(brain)).get_json()["items"]
    assert len(items) == 1
    assert "عيادة النور" in str(items[0]["preview"])
    assert core(brain, lambda s: s.query(Tenant).count()) == 0
    customer_id = core(brain, lambda s: s.query(FcConversationCustomer).filter_by(conversation_ref=str(conv_id_for(brain))).one().customer_id)
    facts = core(brain, lambda s: memory.active_facts(s, customer_id))
    assert facts["city"]["value"] == "بغداد" and facts["employees"]["value"] == 1 and facts["doctors"]["value"] == 3
    assert decision(brain, items[0]).status_code == 200
    assert core(brain, lambda s: s.get(FcCustomer, customer_id).tenant_slug) is not None


def test_account_intake_can_be_canceled_and_does_not_consume_training(brain):
    from modules.finora_core.brain.models import FcApproval
    say(brain, "عيادة اسنان")
    assert "اسم العيادة" in say(brain, "سويلي حساب")
    say(brain, "شلون أضيف مريض؟")
    assert "وقفت" in say(brain, "لا تسويلي حساب")
    say(brain, "اسم العيادة النور ورقمي 07701234567")
    assert core(brain, lambda s: s.query(FcApproval).count()) == 0
