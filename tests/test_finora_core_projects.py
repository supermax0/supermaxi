"""Custom project consultation through the actual webhook/worker/approval paths, isolated channels/DBs."""
import copy
import json
import pytest

from tests.finora_core_support import env, _api, _auth, _messages  # noqa: F401
from tests.test_finora_core_brain import brain, core, FakeProvider  # noqa: F401
from tests.test_finora_core_telegram import telegram, say  # noqa: F401

REQUEST = "اريد تطبيق لحجز ملاعب كرة قدم، الزبون يحجز والمالك يدير الملاعب، اندرويد وايفون ودفع عند الحضور"


def brief(ready=True):
    return {"title": "حجز الملاعب", "kind": "mobile_app", "goal": "تنظيم حجز ملاعب كرة القدم", "audience": "الزبائن ومالكو الملاعب",
            "platforms": ["Android", "iOS"], "requirements": [{"text": "الحجز والدفع عند الحضور", "evidence": REQUEST}],
            "suggestions": [{"title": "تذكير بالحجز", "benefit": "تقليل عدم الحضور"}],
            "pages": [{"id": "venues", "name": "الملاعب", "purpose": "عرض الملاعب المتاحة", "features": ["بحث", "صور", "وقت متاح"],
                       "links": ["booking"], "roles": ["زبون"], "phase": "mvp", "acceptance": ["البحث يعرض الملاعب المتاحة فقط"]},
                      {"id": "booking", "name": "الحجز", "purpose": "حجز وقت بدون تعارض", "features": ["اختيار وقت", "تأكيد", "إلغاء"],
                       "links": ["venues"], "roles": ["زبون", "مالك"], "phase": "mvp", "acceptance": ["يمنع حجز نفس الموعد مرتين"]}],
            "roles": [{"name": "زبون", "permissions": ["حجز وإلغاء حجوزه فقط"]}, {"name": "مالك", "permissions": ["إدارة ملاعبه وحجوزاتها فقط"]}],
            "entities": [{"name": "ملعب", "fields": ["الاسم", "العنوان"], "relatedTo": ["حجز"]}, {"name": "حجز", "fields": ["الوقت", "الزبون"], "relatedTo": ["ملعب"]}],
            "workflows": [{"id": "reserve", "name": "البحث وحجز الموعد", "trigger": "الزبون يريد حجز ملعب",
                           "steps": [{"id": "search", "pageId": "venues", "role": "زبون", "action": "يبحث عن ملعب", "result": "تظهر الملاعب المتاحة",
                                      "next": [{"stepId": "confirm", "condition": "اختار ملعباً ووقتاً"}]},
                                     {"id": "confirm", "pageId": "booking", "role": "زبون", "action": "يؤكد الموعد", "result": "يحفظ الحجز مرة واحدة",
                                      "next": [{"stepId": "search", "condition": "الموعد محجوز؛ يرجع لاختيار وقت آخر"}, {"stepId": "finish", "condition": "الموعد متاح"}]},
                                     {"id": "finish", "pageId": "booking", "role": "مالك", "action": "يراجع الحجز", "result": "حجز مؤكد والدفع عند الحضور", "next": []}],
                           "acceptance": ["تعارض الموعد يرجع للاختيار ولا ينشئ حجزاً مكرراً"]}],
            "integrations": [], "milestones": [{"name": "نسخة أولية", "deliverables": ["بحث وحجز وإدارة"]}, {"name": "تسليم", "deliverables": ["اختبارات وتشغيل"]}],
            "assumptions": ["العميل يوفر المحتوى", "تكلفة متاجر التطبيقات والاستضافة منفصلة"], "exclusions": ["دفع إلكتروني"],
            "risks": ["تعارض الحجز يحتاج اختبار"], "questions": [] if ready else ["تحتاج الدفع الإلكتروني لو عند الحضور؟"], "ready": ready,
            "estimate": {"amount": 1000000, "currency": "IQD", "days": 30, "mvpDays": 10, "basis": "تحليل وتصميم وحجز وصلاحيات واختبارات؛ تقدير غير معتمد"}}


def pending(state):
    return _api(state, "get", "/approvals", headers=state["auth"]).get_json()["items"]


def decision(state, item):
    return _api(state, "post", f"/approvals/{item['id']}/decision", headers=state["auth"], json={"decision": "approved", "planHash": item["planHash"]})


def profile(state, cid="1"):
    return _api(state, "get", f"/customers/{cid}", headers=state["auth"]).get_json()


def approved_offer(telegram):
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST)
    say(telegram, "موافق على الخطة")
    assert decision(telegram, pending(telegram)[0]).status_code == 200
    assert profile(telegram)["project"]["phase"] == "quote_sent"


def price_issues(telegram):
    return [item for item in _api(telegram, "get", "/support/issues", headers=telegram["auth"]).get_json()["items"]
            if item["kind"] == "quote_negotiation"]


def test_discount_dialogue_deduplicates_owner_request_and_preserves_offer(telegram):
    approved_offer(telegram)
    before = profile(telegram)["project"]
    first = say(telegram, "اكو تخفيضات")
    second = say(telegram, "اريت تخفيض على سعر")
    assert "تخفيض" in first and "ميزانية" in first
    assert "تخفيض" in second and first != second and "ميزانية" not in second
    issues = price_issues(telegram)
    assert len(issues) == 1
    assert issues[0]["conversationId"] == "1"
    assert "اكو تخفيضات" in issues[0]["details"] and "اريت تخفيض على سعر" in issues[0]["details"]
    assert "200000" not in first + second
    assert profile(telegram)["project"] == before and pending(telegram) == []
    assert "قيد المراجعة" in say(telegram, "نعم")
    assert profile(telegram)["project"] == before
    assert "اقتراحك للسعر" in say(telegram, "٥٠٠ الف دينار")
    assert len(price_issues(telegram)) == 1 and "٥٠٠ الف دينار" in price_issues(telegram)[0]["details"]
    assert profile(telegram)["project"] == before
    assert "بعد ما عدنا" in say(telegram, "شصار على طلب التخفيض")
    assert profile(telegram)["project"] == before
    # Explicit consent to the unchanged approved offer remains possible; a budget is never consent.
    assert "200000.00" in say(telegram, "موافق على العرض")
    assert profile(telegram)["project"]["phase"] == "awaiting_deposit"
    accepted = profile(telegram)["project"]
    assert "تخفيض" in say(telegram, "ممكن تخفيض قبل ما ادفع؟")
    assert profile(telegram)["project"] == accepted and pending(telegram) == []


def test_quote_discount_negation_and_scope_features_are_not_price_requests():
    from modules.finora_core.brain import project_consultation as project
    draft = {"revision": 1, "quoteHash": "quote", "brief": brief()}
    assert project.negotiate(None, None, "1", draft, "ما اريد تخفيض", "1", "", shadow=True) == "تمام، نكمل على العرض الحالي."
    for value in ["ضيف صفحة خصومات", "كود خصم للمنتجات", "ميزة تخفيض للزبائن", "اريد اخلي تخفيضات", "خصم على البضاعة"]:
        assert project.negotiate(None, None, "1", draft, value, "1", "", shadow=True) is None
    draft["negotiation"] = {"revision": 1, "quoteHash": "quote", "messages": [{"id": "1", "text": "اريد تخفيض"}]}
    assert project.negotiate(None, None, "1", draft, "اي", "2", "توافق على هذا العرض؟", shadow=True) is None
    assert "قيد المراجعة" in project.negotiate(None, None, "1", draft, "اي", "2", "شكد حدود ميزانيتك؟", shadow=True)


def test_unmatched_offer_message_is_discussed_in_context_instead_of_canned_reply(monkeypatch):
    from types import SimpleNamespace
    from modules.finora_core.brain import project_consultation as project
    draft = {"revision": 1, "quoteHash": "quote", "phase": "quote_sent", "brief": brief(), "evidence": []}
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: copy.deepcopy(draft))
    provider = FakeProvider({"answer": "نخلي الاستخدام بسيط حتى موظفك يتابع الحجوزات بسهولة.", "questions": []})
    recent = [{"role": "customer", "text": "موظفي يحتاج تدريب"}, {"role": "finora", "text": "نقدر نجهز شرحاً للحجز."}]
    reply = project.consult(None, SimpleNamespace(), "1", "الموظف ما يعرف يتعامل وياه", provider=provider,
                            message_id="1", recent=recent)
    assert "موظفك" in reply["reply"] and reply["model"] == "fake-model"
    assert "الموظف ما يعرف" in provider.calls[0]["user"] and "نقدر نجهز" in provider.calls[0]["user"]


@pytest.mark.parametrize("message", ["السعر غالي", "ممكن خصم 20%؟", "ميزانيتي 500 الف", "اخر سعر شكد؟", "عندي ميزانية أقل"])
def test_commercial_negotiation_never_rebuilds_or_accepts_plan(telegram, message):
    approved_offer(telegram)
    before = profile(telegram)["project"]
    reply = say(telegram, message)
    assert "المشرف" in reply or "لمشرف" in reply
    assert len(price_issues(telegram)) == 1
    assert profile(telegram)["project"] == before and pending(telegram) == []


def test_discount_is_scoped_and_product_discount_page_is_still_scope_change(telegram):
    approved_offer(telegram)
    before = profile(telegram)["project"]
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST, uid=88888)
    say(telegram, "اريد خصم", uid=88888)
    issues = price_issues(telegram)
    assert len(issues) == 1 and issues[0]["conversationId"] != "1"
    assert profile(telegram)["project"] == before
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, "ضيف صفحة عروض وخصومات")
    assert len(price_issues(telegram)) == 1
    assert profile(telegram)["project"]["revision"] == before["revision"] + 1


def test_discount_preview_does_not_notify_owner_or_change_draft(telegram):
    from modules.finora_core.brain import project_consultation as project
    from modules.finora_core.brain.models import FcCustomer
    approved_offer(telegram)
    before = profile(telegram)["project"]
    def preview(s):
        return project.consult(s, s.get(FcCustomer, 1), "1", "اريد تخفيض", provider=None,
                               message_id="preview-discount", shadow=True)
    assert "وضع التجربة" in core(telegram, preview)["reply"]
    assert price_issues(telegram) == [] and profile(telegram)["project"] == before


def test_full_consultation_quote_review_consent_verified_deposit_and_manifest(telegram):
    telegram["state"]["provider"] = FakeProvider(brief())
    assert "موافق على الخطة" in say(telegram, REQUEST)
    assert pending(telegram) == []
    consent_reply = say(telegram, "موافق على الخطة")
    assert "1000000" not in consent_reply
    items = pending(telegram)
    assert items, (consent_reply, profile(telegram).get("project"), [(m.get("status"), m.get("text")) for m in _messages(telegram, direction="outbound")])
    quote = items[0]
    assert quote["preview"]["project"]["terms"]["amount"] == 1000000
    assert quote["preview"]["depositAmount"] == "200000.00"
    # The owner can edit the exact offer; an old approval no longer authorizes it.
    revised = _api(telegram, "patch", f"/approvals/{quote['id']}/project", headers=telegram["auth"],
                   json={"planHash": quote["planHash"], "terms": {"amount": 1200000, "currency": "IQD", "days": 35, "mvpDays": 12}})
    assert revised.status_code == 200, revised.get_json()
    assert decision(telegram, quote).status_code == 409
    quote = revised.get_json()["approval"]
    assert decision(telegram, quote).status_code == 200
    assert profile(telegram)["project"]["phase"] == "quote_sent"
    sent = "\n".join(m["text"] or "" for m in _messages(telegram, direction="outbound"))
    assert "1,200,000" in sent and "35 يوم" in sent and "12 يوم" in sent
    assert "240000.00" in say(telegram, "موافق على العرض")
    assert profile(telegram)["project"]["phase"] == "awaiting_deposit"
    assert "ما ثبتنا" in say(telegram, "ما دفعت بعد")
    assert pending(telegram) == []
    assert "يتحقق" in say(telegram, "دفعت العربون")
    payment = pending(telegram)[0]
    assert payment["preview"]["projectAction"] == "confirm_project_deposit"
    assert decision(telegram, payment).status_code == 409  # owner must record verification first
    verified = _api(telegram, "patch", f"/approvals/{payment['id']}/project", headers=telegram["auth"],
                    json={"planHash": payment["planHash"], "paymentVerified": True, "paymentReference": "bank-receipt-verified-20"})
    assert verified.status_code == 200, verified.get_json()
    assert decision(telegram, verified.get_json()["approval"]).status_code == 200
    data = _api(telegram, "get", "/conversations/1/project/manifest", headers=telegram["auth"]).get_json()
    assert data["handoffReady"] and data["depositVerified"] and data["automaticExecutionEnabled"] is False
    assert len(data["project"]["pages"]) == 2 and data["executor"] is None
    old_project = profile(telegram)["project"]
    assert "محفوظين" in say(telegram, "ضيف صفحة جديدة للعروض")
    assert profile(telegram)["project"] == old_project
    assert "الحجز" in say(telegram, "اشرح صفحة الحجز")
    assert profile(telegram)["project"] == old_project
    assert "الحجز" in say(telegram, "شلون تشتغل صفحة الحجز بالخطة؟")
    assert profile(telegram)["project"] == old_project
    from models.core.tenant import Tenant
    assert core(telegram, lambda s: s.query(Tenant).count()) == 0
    from modules.finora_core.models import FcOperatorRole
    def restrict(s):
        s.add(FcOperatorRole(superadmin_id=1, role="read_only")); s.commit()
    core(telegram, restrict)
    restricted = _auth(telegram)
    assert _api(telegram, "get", "/conversations/1/project/manifest", headers=restricted).status_code == 403
    assert _api(telegram, "patch", f"/approvals/{quote['id']}/project", headers=restricted, json={}).status_code == 403


def test_dialogue_no_quote_before_scope_no_other_customer_consent_or_silent_changes(telegram):
    telegram["state"]["provider"] = FakeProvider(brief(False), brief())
    assert "الدفع" in say(telegram, REQUEST)
    assert pending(telegram) == []
    assert "موافق على الخطة" in say(telegram, "عند الحضور، بدون دفع إلكتروني")
    say(telegram, "موافق", uid=88888)
    assert pending(telegram) == []
    say(telegram, "موافق على الخطة")
    old = pending(telegram)[0]
    assert _api(telegram, "patch", f"/approvals/{old['id']}/project", json={}).status_code == 401
    invalid = _api(telegram, "patch", f"/approvals/{old['id']}/project", headers=telegram["auth"],
                   json={"planHash": old["planHash"], "terms": {"amount": 500, "currency": "USD", "days": 5, "mvpDays": 10}})
    assert invalid.status_code == 400
    say(telegram, "ضيف صفحة عروض وخصومات")
    assert pending(telegram) == [] and decision(telegram, old).status_code == 409
    assert "مراجعة" not in (say(telegram, "شكرا") or "")


def test_invalid_model_graph_and_ungrounded_facts_do_not_replace_previous_draft(telegram):
    good = brief()
    broken = copy.deepcopy(good); broken["pages"][0]["links"] = ["another-customer-page"]
    telegram["state"]["provider"] = FakeProvider(good, broken)
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    assert "واجهت مشكلة" in say(telegram, "عدل الفكرة")
    assert profile(telegram)["project"] == before and pending(telegram) == []


def test_undelivered_offer_cannot_be_accepted_and_can_be_retried(telegram):
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST); say(telegram, "موافق على الخطة")
    quote = pending(telegram)[0]
    telegram["telegram"].fail["sendMessage"] = 500
    assert decision(telegram, quote).status_code == 200
    assert profile(telegram)["project"]["phase"] == "quote_ready"
    say(telegram, "موافق على العرض")
    assert profile(telegram)["project"]["customerConsent"] is None
    telegram["telegram"].fail.pop("sendMessage")
    retried = _api(telegram, "post", "/conversations/1/project/send-offer", headers=telegram["auth"], json={})
    assert retried.status_code == 200 and retried.get_json()["project"]["phase"] == "quote_sent"
    say(telegram, "موافق على العرض")
    assert profile(telegram)["project"]["phase"] == "awaiting_deposit"


def test_shadow_does_not_authorize_scope_quotes_or_payment(telegram):
    from modules.finora_core.store import set_setting
    from modules.finora_core.brain.models import FcShadowProposal
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    def enable(s):
        set_setting(s, "flag:AI_SHADOW_MODE", "on", "test"); s.commit()
    core(telegram, enable)
    say(telegram, "موافق على الخطة")
    assert pending(telegram) == [] and profile(telegram)["project"] == before
    assert core(telegram, lambda s: s.query(FcShadowProposal).count()) == 1


@pytest.mark.parametrize("value", ["اريد احمل تطبيق فينورا", "شلون اضيف موقع العيادة", "لا اريد تطبيق", "اريد حساب تجريبي"])
def test_existing_product_requests_are_not_custom_projects(value):
    from modules.finora_core.brain.project_consultation import requested
    assert not requested(value)


def test_long_page_plan_is_split_without_losing_pages_or_consent_prompt():
    from modules.finora_core.brain.project_consultation import chunks, full_plan_text, validate_brief
    data = brief()
    for i in range(3, 18):
        page = copy.deepcopy(data["pages"][0]); page["id"], page["name"] = f"page{i}", f"صفحة {i}"
        page["features"] = ["إدارة البيانات واختبار الحالة والاستثناءات " * 3] * 4
        page["phase"] = "later"
        data["pages"].append(page)
    validate_brief(data, [{"text": REQUEST}])
    parts = chunks(full_plan_text(data))
    assert len(parts) > 2 and all(len(part) <= 1800 for part in parts)
    assert "صفحة 17" in "\n".join(parts) and "عرض منفصل" in parts[-1]


def test_default_overview_contains_names_not_specifications_or_private_estimate():
    from modules.finora_core.brain.project_consultation import chunks, scope_text
    data = brief()
    reply = scope_text(data)
    assert len(reply) < 700 and "\n\nصفحات النسخة الأولى:\n• الملاعب\n• الحجز" in reply
    assert "موافق على الخطة" in reply and "دز الخطة كاملة" in reply
    assert chunks(reply) == [reply]  # Actual channel delivery preserves the readable paragraph spacing.
    for hidden in ("يمنع حجز نفس الموعد", "إلغاء", "الموعد محجوز", "1000000", "30 يوم", "تكلفة متاجر التطبيقات", "تذكير بالحجز"):
        assert hidden not in reply


@pytest.mark.parametrize("client_text", ["دز الخطة كاملة", "ارسل تفاصيل الخطة", "اريد الخطة بالتفصيل"])
def test_explicit_full_plan_is_read_only_and_retains_delivery_proof(telegram, client_text):
    provider = FakeProvider(brief())
    telegram["state"]["provider"] = provider
    overview = say(telegram, REQUEST)
    assert "يمنع حجز نفس الموعد" not in overview
    before = profile(telegram)["project"]
    reply = say(telegram, client_text)
    assert "يمنع حجز نفس الموعد" in reply and "الموعد محجوز" in reply and "مراحل التسليم" in reply
    assert "1000000" not in reply and "30 يوم" not in reply
    assert profile(telegram)["project"] == before and len(provider.calls) == 1 and pending(telegram) == []
    say(telegram, "موافق على الخطة")
    assert len(pending(telegram)) == 1


@pytest.mark.parametrize("client_text", ["ملخص الخطة", "شنو الصفحات بالخطة", "ارسل ملخص الخطة بس اسماء الصفحات", "لا ترسل الخطة كاملة اريد ملخص"])
def test_overview_request_never_dumps_full_plan(client_text):
    from modules.finora_core.brain.project_consultation import explain_plan, explanation_requested
    from modules.finora_core.brain.extract import normalize
    data = brief()
    assert explanation_requested(data, client_text)
    reply = explain_plan({"brief": data}, normalize(client_text))
    assert "• الملاعب" in reply and "• الحجز" in reply
    assert "الميزات:" not in reply and "الصلاحيات:" not in reply and "الموعد محجوز" not in reply


def test_specific_page_details_do_not_expand_to_the_rest_of_the_plan(telegram):
    provider = FakeProvider(brief())
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    reply = say(telegram, "اريد تفاصيل صفحة الحجز")
    assert "الميزات:\n• اختيار وقت" in reply and "نفحصها عند التسليم" in reply
    assert "مسار العمل:" not in reply and "صفحة «الملاعب»" not in reply
    assert profile(telegram)["project"] == before and len(provider.calls) == 1


@pytest.mark.parametrize("damage", ["missing", "page", "role", "edge", "unreachable", "no_end", "coverage"])
def test_internal_workflow_rejects_missing_access_links_and_dead_ends(damage):
    from modules.finora_core.brain.project_consultation import validate_brief
    data = brief(); steps = data["workflows"][0]["steps"]
    if damage == "missing":
        del data["workflows"]
    elif damage == "page":
        steps[0]["pageId"] = "other_customer_page"
    elif damage == "role":
        steps[0]["role"] = "مالك"
    elif damage == "edge":
        steps[0]["next"][0]["stepId"] = "missing"
    elif damage == "unreachable":
        extra = copy.deepcopy(steps[-1]); extra["id"] = "island"; steps.append(extra)
    elif damage == "no_end":
        steps[-1]["next"] = [{"stepId": "search", "condition": "يرجع"}]
    elif damage == "coverage":
        steps[0]["pageId"] = "booking"
    with pytest.raises((ValueError, __import__("jsonschema").ValidationError)):
        validate_brief(data, [{"text": REQUEST}], require_workflows=True)


def test_legacy_agreed_plan_remains_valid_without_inventing_a_workflow():
    from modules.finora_core.brain.project_consultation import checked_scope
    data = brief(); del data["workflows"]
    before = copy.deepcopy(data)
    checked_scope({"brief": data, "evidence": [{"text": REQUEST}]})
    assert data == before
    assert "workflows" not in data


def test_discovery_cannot_silently_stop_without_a_follow_up():
    from modules.finora_core.brain.project_consultation import validate_brief
    data = brief(False); data["questions"] = []
    with pytest.raises(ValueError, match="Discovery requires"):
        validate_brief(data, [{"text": REQUEST}])


def test_generic_website_request_requires_discovery_instead_of_guessing_store_pages():
    from modules.finora_core.brain.project_consultation import validate_brief
    data = brief(); data["requirements"] = [{"text": "موقع", "evidence": "اريد موقع لمحل اجهزة"}]
    parsed = validate_brief(data, [{"text": "اريد موقع لمحل اجهزة"}])
    assert not parsed["ready"] and len(parsed["questions"]) == 2
    assert parsed["estimate"] is None and parsed["pages"] == []


@pytest.mark.parametrize("audience", ["زبائن", "زباين", "موظفين", "موضفين", "موطفين"])
def test_clothing_audience_answer_is_not_asked_again_after_normalization(audience):
    from modules.finora_core.brain.project_consultation import validate_brief
    request = f"اريد تطبيق متجر لبيع الملابس يستخدمه {audience}"
    data = brief()
    data["requirements"] = [{"text": "متجر الملابس", "evidence": request}]
    parsed = validate_brief(data, [{"text": request}])
    assert parsed["ready"] and parsed["questions"] == []
    assert parsed["pages"] and parsed["estimate"] is not None


def test_one_structural_repair_produces_valid_graph_and_accounts_for_usage():
    from modules.finora_core.brain.project_consultation import generate_brief
    bad = brief(); bad["entities"][0]["relatedTo"] = ["undefined entity"]
    class CapturedProvider(FakeProvider):
        def generate_structured(self, **kwargs):
            schemas.append(copy.deepcopy(kwargs["schema"]))
            result = super().generate_structured(**kwargs)
            fields = json.loads(kwargs["user"]).get("REPLACE_ONLY_FIELDS")
            if fields:
                result.data = {key: result.data[key] for key in fields}
            return result
    schemas = []
    provider = CapturedProvider(bad, brief())
    data, result = generate_brief(provider, [{"text": REQUEST}], None)
    assert len(provider.calls) == 2 and data["ready"] and result.input_tokens == 240
    for schema in schemas[:1]:
        quotes = schema["properties"]["requirements"]["items"]["properties"]["evidence"]["enum"]
        assert REQUEST in quotes and all(quote in REQUEST for quote in quotes)


@pytest.mark.parametrize("answer, expected", [
    ("أنصح بطلب بدون حساب بالبداية حتى نسهل الشراء؛ الحساب اختياري لحفظ العناوين.", "الحساب اختياري"),
    ("هذا يكلف 400 دولار", "تعذر تجهيز نصيحة دقيقة"),
])
def test_advisory_question_answers_options_without_replacing_scope_or_revealing_estimate(telegram, answer, expected):
    provider = FakeProvider(brief(), {"answer": answer, "questions": ["الدفع عند الاستلام لو إلكتروني؟"]})
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    original = profile(telegram)["project"]
    reply = say(telegram, "تنصحني بطلب بدون حساب لو حساب إلزامي؟ وشلون نخلي سياسة الاستبدال؟")
    assert expected in reply
    assert "رتبت مشروع" not in reply
    assert profile(telegram)["project"] == original
    assert pending(telegram) == []
    payload = json.loads(provider.calls[-1]["user"])
    assert "estimate" not in payload["UNTRUSTED_SCOPE"]
    say(telegram, "موافق على الخطة")
    assert len(pending(telegram)) == 1  # Advice never replaces proof of sending the actual scope.


@pytest.mark.parametrize("question, explanation", [
    ("شلون تشتغل صفحة الحجز بالخطة؟", True),
    ("اشرح صفحة الحجز", True),
    ("شلون نخلي سياسة الاستبدال مناسبة؟", False),
    ("تنصحني بتسجيل حساب لو بدون حساب؟", False),
])
def test_explanation_is_for_a_page_not_every_advisory_how_question(question, explanation):
    from modules.finora_core.brain.project_consultation import explanation_requested
    assert explanation_requested(brief(), question) is explanation


@pytest.mark.parametrize("broken", [None, "payment", "delivery", "returns", "staff"])
def test_clothing_plan_covers_literal_operational_rules_and_limited_staff(broken):
    from modules.finora_core.brain.project_consultation import validate_brief
    request = "اريد تطبيق لبيع ملابس للزبائن، دفع عند الاستلام وتوصيل داخل بغداد، واستبدال خلال 7 أيام. الموظف يستلم الطلبات ويحدث حالتها فقط"
    data = brief()
    data["requirements"] = [{"text": "متجر الملابس", "evidence": request}]
    data["roles"].append({"name": "موظف", "permissions": ["عرض الطلبات", "تغيير حالة الطلب"]})
    data["pages"][0]["features"] += ["دفع عند الاستلام", "توصيل داخل بغداد", "استبدال خلال 7 أيام"]
    if broken == "staff":
        data["roles"][-1]["permissions"].append("تعديل الأسعار")
    elif broken:
        index = {"payment": -3, "delivery": -2, "returns": -1}[broken]
        data["pages"][0]["features"].pop(index)
    if broken:
        with pytest.raises(ValueError):
            validate_brief(data, [{"text": request}])
    else:
        assert validate_brief(data, [{"text": request}])["ready"]


def test_new_delivery_choice_supersedes_old_city_constraint():
    from modules.finora_core.brain.project_consultation import operational_issues
    assert operational_issues(brief(), [{"text": "توصيل داخل بغداد"}, {"text": "التوصيل يصير فقط بأربيل بدل بغداد"}]) == []


def test_real_reported_followups_and_command_burst_read_existing_plan_without_rebuilding(telegram):
    provider = FakeProvider(brief())
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    assert "هلا بيك" in say(telegram, "مرحبا")
    assert "تفضل" in say(telegram, "موحبا\n/start\nمرحبا")
    assert "أسمعك" in say(telegram, "مرحبا")
    for value in ("شنو صفحات الي راح سويهن", "ها شوف صفحات", "وريني كل الصفحات"):
        reply = say(telegram, value)
        assert "• الملاعب" in reply and "• الحجز" in reply
        assert "الميزات:" not in reply and "تعذر" not in reply and brief()["goal"] not in reply
    assert "جاهزة للنقاش" in say(telegram, "سويلي تطبيق متجر الكتروني")
    assert "زر المايك" in say(telegram, "/voice")
    assert "اكتب شنو تحتاج" in say(telegram, "/help")
    assert profile(telegram)["project"] == before and len(provider.calls) == 1 and pending(telegram) == []


def test_multiline_customer_quotes_are_not_sent_as_provider_enum_control_literals():
    from modules.finora_core.brain.project_consultation import generate_brief
    bad = brief(); bad["pages"][0]["links"] = ["missing"]
    class StrictProvider(FakeProvider):
        def generate_structured(self, **kwargs):
            choices = kwargs["schema"]["properties"].get("requirements", {}).get("items", {}).get("properties", {}).get("evidence", {}).get("enum", [])
            assert (choices or "REPLACE_ONLY_FIELDS" in json.loads(kwargs["user"])) and all(not any(ord(char) < 32 for char in quote) for quote in choices)
            assert all(quote in multiline for quote in choices)
            result = super().generate_structured(**kwargs)
            fields = json.loads(kwargs["user"]).get("REPLACE_ONLY_FIELDS")
            if fields:
                result.data = {key: result.data[key] for key in fields}
            return result
    multiline = REQUEST + "\nواريد لوحة\tللمالك."
    provider = StrictProvider(bad, brief())
    data, _ = generate_brief(provider, [{"id": "1", "text": multiline}], None)
    assert data["ready"] and len(provider.calls) == 2


def test_discovery_continues_last_question_without_repeating_intro_and_old_suggestions(telegram):
    first = brief(False)
    second = copy.deepcopy(first); second["questions"] = ["تحب إشعار بالحجز للمالك أيضاً؟"]
    provider = FakeProvider(first, second)
    telegram["state"]["provider"] = provider
    previous_reply = say(telegram, REQUEST)
    reply = say(telegram, "عند الحضور، وبدون دفع إلكتروني")
    assert first["goal"] not in reply and first["suggestions"][0]["title"] not in reply
    assert reply == second["questions"][0]
    history = json.loads(provider.calls[-1]["user"])["RECENT_DIALOGUE"]
    assert any(row["role"] == "finora" and first["questions"][0] in row["text"] for row in history)
    assert any(row["role"] == "customer" and "عند الحضور" in row["text"] for row in history)
    assert previous_reply and pending(telegram) == []


def test_advice_receives_previous_assistant_question_and_latest_answer(telegram):
    provider = FakeProvider(brief(), {"answer": "الأفضل نخلي التأكيد قبل تثبيت الحجز حتى نمنع التعارض.", "questions": []})
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    assert "نمنع التعارض" in say(telegram, "شنو تنصحني حتى ما يصير حجز مكرر؟")
    payload = json.loads(provider.calls[-1]["user"])
    assert payload["RECENT_DIALOGUE"] and any(row["role"] == "finora" for row in payload["RECENT_DIALOGUE"])
    assert "estimate" not in payload["UNTRUSTED_SCOPE"] and profile(telegram)["project"] == before


def test_repeated_generation_failure_is_truthful_and_does_not_block_page_questions(telegram):
    from modules.finora_core.brain.provider import ProviderError
    provider = FakeProvider(brief(), ProviderError("invalid_json_schema", "safe error"))
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    first = say(telegram, "عدل الفكرة")
    second = say(telegram, "عدل الفكرة")
    assert "واجهت مشكلة" in first and "التعديل بعده ما اكتمل" in second and first != second
    assert "• الحجز" in say(telegram, "ها شوف صفحات")
    assert profile(telegram)["project"] == before and len(provider.calls) == 3 and pending(telegram) == []


def test_casual_yes_after_page_discussion_is_not_financial_or_scope_consent(telegram):
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST)
    say(telegram, "ها شوف صفحات")
    before = profile(telegram)["project"]
    assert "أي صفحة" in say(telegram, "اي")
    assert pending(telegram) == [] and profile(telegram)["project"] == before
    say(telegram, "موافق على الخطة")
    assert len(pending(telegram)) == 1


@pytest.mark.parametrize("question", ["ليش ننطي شراء بدون حساب؟", "وضح خيارات الدفع", "شنو نصايحك للمشروع"])
def test_short_followup_questions_are_discussed_instead_of_rebuilding_or_repeating_status(telegram, question):
    provider = FakeProvider(brief(), {"answer": "خلّينا نسهّل الحجز على الزبون ونقلل الخطوات المطلوبة.", "questions": []})
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    assert "نقلل الخطوات" in say(telegram, question)
    assert profile(telegram)["project"] == before and pending(telegram) == []


def test_approved_offer_is_not_repeated_for_an_acknowledgement(telegram):
    telegram["state"]["provider"] = FakeProvider(brief())
    say(telegram, REQUEST); say(telegram, "موافق على الخطة")
    assert decision(telegram, pending(telegram)[0]).status_code == 200
    before = profile(telegram)["project"]
    reply = say(telegram, "حلو")
    assert "1,000,000" not in reply and len(reply) < 100
    say(telegram, "اي")
    assert profile(telegram)["project"] == before
    assert "1,000,000" in say(telegram, "شنو السعر والمدة؟")
    say(telegram, "موافق على العرض")
    assert profile(telegram)["project"]["phase"] == "awaiting_deposit"


def test_bare_agreement_after_long_scope_reply_keeps_the_actual_confirmation_context(telegram):
    data = brief()
    for index in range(12):
        page = copy.deepcopy(data["pages"][0])
        page.update(id=f"later_{index}", name=f"إدارة التقارير والإحصائيات التفصيلية للمرحلة {index}", phase="later")
        data["pages"].append(page)
    telegram["state"]["provider"] = FakeProvider(data)
    assert len(say(telegram, REQUEST)) > 800
    say(telegram, "اي")
    assert len(pending(telegram)) == 1 and profile(telegram)["project"]["phase"] == "internal_review"


def test_feasibility_ideas_are_discussed_without_rebuilding_the_agreed_draft(telegram):
    provider = FakeProvider(brief(),
                            {"answer": "نقدر نناقش عرض منتجات تكميلية بعد مراجعة فائدتها للزبون.", "questions": []},
                            {"answer": "نناقش اقتراحات السلة بحيث تكون إضافات اختيارية وما تعطل إكمال الطلب.", "questions": []},
                            {"answer": "نناقش ربط المقترحات بنوع القطعة حتى يظهر الحزام أو الجوارب المناسبة.", "questions": []})
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    for question in ["زين من يكمل الطلب ويروح للسله نكدر نخلي منتجات ذات صله او تكميليه يعني جواريب او ملابس داخليه او حزام وهكذا",
                     "ممكن نضيف اقتراحات داخل السلة؟", "يصير نربط الاقتراحات بنوع القطعة؟"]:
        assert "نناقش" in say(telegram, question)
    assert len(provider.calls) == 4
    assert all("CURRENT_QUESTION" in json.loads(call["user"]) for call in provider.calls[1:])
    assert profile(telegram)["project"] == before and pending(telegram) == []
    from modules.finora_core.brain.project_consultation import exploring_idea
    assert not exploring_idea("ضيف المنتجات التكميلية للخطة")


def test_followup_about_plan_failure_does_not_invent_a_cause_or_a_saved_change(telegram):
    from modules.finora_core.brain.provider import ProviderError
    from modules.finora_core.brain.project_consultation import failure_followup
    provider = FakeProvider(brief(), ProviderError("timeout", "safe failure"))
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST)
    before = profile(telegram)["project"]
    first = say(telegram, "عدل الفكرة")
    assert "واجهت مشكلة" in first
    reply = say(telegram, "ليش اكو خطاء")
    assert "ما اكتملت" in reply and "سبب ذاك الخطأ يحتاج مراجعة" in reply
    assert len(provider.calls) == 4 and profile(telegram)["project"] == before
    assert not failure_followup("ليش خطأ بتسجيل الدخول؟", [{"role": "finora", "text": first}])


def test_legacy_reset_discards_old_constraints_and_previous_brief():
    from modules.finora_core.brain.project_consultation import generate_brief
    new = "اريد تطبيق يعرض منتجاتي للزبائن، تصفح بدون حساب بس اذا يريد يطلب لازم يسوي حساب"
    discovery = brief(False)
    discovery["requirements"] = [{"text": "عرض وشراء المنتجات", "evidence": new}]
    discovery["pages"] = []; discovery["workflows"] = []; discovery["roles"] = []
    discovery["questions"] = ["شنو طريقة الدفع والتوصيل اللي تحتاجها؟"]
    discovery["estimate"] = None
    provider = FakeProvider(discovery)
    data, _ = generate_brief(provider, [{"text": REQUEST + " وتوصيل داخل بغداد واستبدال خلال 7 أيام"},
                                      {"text": "احذف كلشي"}, {"text": new}], brief(),
                             recent=[{"role": "customer", "text": REQUEST}, {"role": "customer", "text": "احذف كلشي"},
                                     {"role": "customer", "text": new}])
    payload = json.loads(provider.calls[0]["user"])
    assert payload["CUSTOMER_MESSAGES"] == [{"text": new}] and payload["PREVIOUS_BRIEF"] is None
    assert payload["CURRENT_CUSTOMER_MESSAGE"] == new
    assert not any(REQUEST in row["text"] for row in payload["RECENT_DIALOGUE"])
    assert not data["ready"] and len(provider.calls) == 1


def test_targeted_workflow_correction_can_correct_itself_again_without_losing_requirements():
    from modules.finora_core.brain.project_consultation import generate_brief
    original = brief()
    healthy = copy.deepcopy(original["workflows"][0]); healthy["id"] = "other_flow"
    original["workflows"].append(healthy)
    broken = copy.deepcopy(original)
    broken["workflows"][0]["steps"][-1]["next"] = [{"stepId": "search", "condition": "يرجع"}]
    still_bad = {"workflows": [copy.deepcopy(broken["workflows"][0])]}
    fixed = {"workflows": [copy.deepcopy(original["workflows"][0])]}
    provider = FakeProvider(broken, still_bad, fixed)
    data, result = generate_brief(provider, [{"text": REQUEST}], None)
    assert len(provider.calls) == 3 and data == original
    assert json.loads(provider.calls[1]["user"])["REPLACE_ONLY_FIELDS"] == ["workflows"]
    assert json.loads(provider.calls[1]["user"])["WORKFLOWS_TO_REPLACE"] == ["reserve"]
    assert result.input_tokens == 360 and result.output_tokens == 120


@pytest.mark.parametrize("code, recovered", [("timeout", True), ("invalid_api_key", False), ("insufficient_quota", False)])
def test_project_retries_transient_failures_only(code, recovered):
    from modules.finora_core.brain.project_consultation import generate_brief
    from modules.finora_core.brain.provider import ProviderError
    provider = FakeProvider(ProviderError(code, "safe failure"), brief())
    if recovered:
        data, _ = generate_brief(provider, [{"text": REQUEST}], None)
        assert data["ready"] and len(provider.calls) == 2
    else:
        with pytest.raises(ProviderError):
            generate_brief(provider, [{"text": REQUEST}], None)
        assert len(provider.calls) == 1


def test_secret_like_output_is_never_repaired_or_saved():
    from modules.finora_core.brain.project_consultation import generate_brief
    bad = brief(); bad["assumptions"] = ["sk-proj-" + "x" * 20]
    provider = FakeProvider(bad, brief())
    with pytest.raises(ValueError, match="Secret-like"):
        generate_brief(provider, [{"text": REQUEST}], None)
    assert len(provider.calls) == 1


def test_new_checkout_answer_requires_public_browsing_and_account_before_ordering():
    from modules.finora_core.brain.project_consultation import operational_issues
    data = brief(); data["pages"][0]["name"] = "المنتجات"; data["pages"][1]["name"] = "إكمال الطلب"
    request = "نعم شراء فعلي مع سله واكمال طلب\nتصفح بدون حساب بس اذا يريد يطلب لازم يسوي حساب"
    evidence = [{"text": "أريد شراء بدون حساب"}, {"text": request}]
    assert len(operational_issues(data, evidence)) == 2
    data["pages"][0]["features"].append("تصفح المنتجات بدون حساب")
    data["pages"][1]["features"].append("إنشاء حساب وتسجيل الدخول قبل تأكيد الطلب")
    assert operational_issues(data, evidence) == []
    data["pages"][1]["features"].append("شراء بدون حساب")
    assert any("contradicted" in issue for issue in operational_issues(data, evidence))


def test_actual_reset_clears_scope_evidence_and_invalidates_only_this_project(telegram):
    provider = FakeProvider(brief())
    telegram["state"]["provider"] = provider
    say(telegram, REQUEST); say(telegram, "موافق على الخطة")
    old = pending(telegram)[0]
    assert "نبدأ بفكرة جديدة" in say(telegram, "احذف كلشي")
    project = profile(telegram)["project"]
    assert project["phase"] == "discovery" and project["brief"]["pages"] == []
    assert not project["terms"] and not project["scopeConsent"] and not project["depositVerified"]
    assert pending(telegram) == [] and decision(telegram, old).status_code == 409
    assert len(provider.calls) == 1


@pytest.mark.parametrize("phase", ["deposit_review", "execution_ready"])
def test_reset_cannot_erase_a_project_under_deposit_review_or_verified_payment(monkeypatch, phase):
    from types import SimpleNamespace
    from modules.finora_core.brain import project_consultation as project, support
    draft = {"phase": phase, "brief": brief(), "depositVerified": phase == "execution_ready"}
    before = copy.deepcopy(draft); reports = []
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: draft)
    monkeypatch.setattr(support, "report", lambda *args, **kwargs: reports.append(kwargs))
    monkeypatch.setattr(project, "save", lambda *args, **kwargs: pytest.fail("Reset must preserve payment state"))
    result = project.consult(None, SimpleNamespace(id="customer"), "1", "احذف كلشي",
                             provider=None, message_id="request")
    assert "العربون الحاليين محفوظين" in result["reply"] and draft == before
    assert reports[0]["kind"] == "project_change" and result["action"] is None


def test_literal_exchange_rule_is_grounded_without_regenerating_healthy_pages():
    from modules.finora_core.brain.project_consultation import generate_brief
    request = "اريد متجر لبيع الملابس للزبائن، استبدال خلال 7 أيام للقطعة غير المستخدمة"
    data = brief(); data["pages"][1]["name"] = "إكمال الطلب"
    data["requirements"] = [{"text": "سياسة الاستبدال", "evidence": request}]
    provider = FakeProvider(data)
    result, _ = generate_brief(provider, [{"text": request}], None)
    assert len(provider.calls) == 1 and result["ready"]
    assert "استبدال خلال 7 أيام للقطعة غير المستخدمة" in result["pages"][1]["features"]
    assert result["workflows"] == brief()["workflows"]


@pytest.mark.parametrize("source", ["هل استبدال خلال 7 أيام مناسب؟", "ما اريد استبدال خلال 7 أيام"])
def test_grounding_does_not_turn_exchange_questions_or_rejections_into_features(source):
    from modules.finora_core.brain.project_consultation import ground_exchange_policy
    data = brief(); data["pages"][1]["name"] = "إكمال الطلب"; before = copy.deepcopy(data)
    assert ground_exchange_policy(data, [{"text": source}]) == before
