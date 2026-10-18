"""Regressions from isolated real-model customer conversations, without channel or account writes."""
import copy
import json
from types import SimpleNamespace

import pytest

from modules.finora_core.brain import project_consultation as project
from modules.finora_core.brain.provider import ProviderError
from tests.test_finora_core_brain import FakeProvider
from tests.test_finora_core_projects import brief, REQUEST
from tests.test_finora_core_understanding import interpretation


@pytest.mark.parametrize("value", [
    "أريد نظام ويب خاص لعيادة أسنان. الطبيب يشوف العلاج. ما أريد التشخيص بالذكاء ولا وصف علاج تلقائي.",
    "أريد تطبيق أندرويد للمندوبين مع لوحة ويب للمشرف. ما أريد تتبع مباشر ولا تطبيق للزبون.",
    "أريد منصة ويب دورات مسجلة بدون بث مباشر.",
    "أريد نظام ويب لتأجير معدات ولا أريد بيع المعدات.",
    "أريد موقع فيه تحميل ملفات، والتسجيل عند إكمال الطلب فقط.",
    "لا أريد تطبيق، أريد موقع لمتجر ملابس.",
    "I need a website for my shop, not a mobile app.",
])
def test_project_exclusions_do_not_cancel_affirmative_request(value):
    assert project.requested(value)


@pytest.mark.parametrize("value", [
    "لا أريد تطبيق", "ما أريد موقع", "مو أريد نظام خاص", "لا أحتاج برنامج مخصص",
    "أريد تسجيل دخول فينورا", "أريد تحميل تطبيق فينورا", "تحميل تطبيق", "I do not need a website",
    "شلون أضيف زبون بفينورا؟",
])
def test_refusal_and_existing_product_help_do_not_start_custom_project(value):
    assert not project.requested(value)


def offer():
    return {"brief": brief(), "revision": 4, "phase": "quote_sent", "evidence": [], "quoteHash": "approved",
            "terms": {"amount": 800000, "currency": "IQD", "days": 25, "mvpDays": 10},
            "customerConsent": None, "depositVerified": False}


@pytest.mark.parametrize("understood", [False, True])
def test_no_change_keeps_exact_offer_and_never_calls_provider_or_invalidates(monkeypatch, understood):
    draft = offer(); original = copy.deepcopy(draft)
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: draft)
    monkeypatch.setattr(project, "save", lambda *args, **kwargs: pytest.fail("Must not save"))
    monkeypatch.setattr(project, "_invalidate", lambda *args, **kwargs: pytest.fail("Must not invalidate"))
    provider = FakeProvider({})
    value = "هسه لا تغير شي، خلي المشرف يشوفه ونتفاهم بعدين."
    result = project.consult(None, None, "own", value, provider=provider, message_id="no-change",
                             understanding=interpretation(value, intent="confirmation", topic="custom_project") if understood else None)
    assert "مثل ما هنّه" in result["reply"] and result["action"] is None
    assert draft == original and provider.calls == []


def test_no_change_to_one_section_does_not_suppress_requested_addition():
    assert not project.leave_unchanged("لا تغير شي بالأسعار بس ضيف صفحة تقارير")
    assert not project.leave_unchanged("لا تغير شي بالأسعار وغير مدة التسليم")


@pytest.mark.parametrize('value', [
    "مثلا من داخل تفاصيل المنتج\nنكدر نختار الحجم مال شاشه\n32 43 50 وهكذا ومن نختار حجم تطلع الفيديو وصور والسعرالخاصه بي",
    "من نختار المقاس يطلع السعر الخاص بالمنتج والصور مالته؟",
])
@pytest.mark.parametrize('understood', [False, True])
def test_product_variant_prices_are_advice_even_when_analysis_is_unavailable(monkeypatch, value, understood):
    draft = offer(); draft['phase'] = 'discovery'
    original = copy.deepcopy(draft)
    monkeypatch.setattr(project, 'load', lambda *args, **kwargs: draft)
    monkeypatch.setattr(project, 'save', lambda *args, **kwargs: pytest.fail('Advice must not rewrite scope'))
    monkeypatch.setattr(project, 'generate_brief', lambda *args, **kwargs: pytest.fail('Question must not rebuild scope'))
    provider = FakeProvider({'answer': 'إي، كل حجم يرتبط بسعره وصوره وفيديوه؛ وتحديث الاختيار يحدّث تفاصيل العرض.', 'questions': []})
    result = project.consult(None, None, 'own', value, provider=provider, message_id='variant-question',
                             understanding=interpretation(value, topic='custom_project') if understood else None)
    assert 'كل حجم' in result['reply'] and 'يراجع المشرف' not in result['reply']
    assert result['action'] is None and draft == original and provider.calls


@pytest.mark.parametrize('value', ['السعر والمدة', 'شكد سعر المشروع؟', 'تفاصيل العرض', 'شكد يكلف؟'])
def test_real_development_quote_questions_still_route_to_commercial_terms(value):
    assert project.commercial_terms_requested(value)


def test_generic_product_details_explains_unique_saved_page_without_rebuilding(monkeypatch):
    draft = offer(); draft['phase'] = 'scope_review'
    page = draft['brief']['pages'][0]; page['name'] = 'تفاصيل الشاشة'
    draft['brief']['pages'] = [page]
    original = copy.deepcopy(draft)
    monkeypatch.setattr(project, 'load', lambda *args, **kwargs: draft)
    monkeypatch.setattr(project, 'save', lambda *args, **kwargs: pytest.fail('Page explanation must not change draft'))
    monkeypatch.setattr(project, 'generate_brief', lambda *args, **kwargs: pytest.fail('Page explanation must not regenerate'))
    provider = FakeProvider({})
    result = project.consult(None, None, 'own', 'تفاصيل المنتج', provider=provider, message_id='details',
                             understanding=interpretation('تفاصيل المنتج', intent='request', topic='custom_project'))
    assert 'صفحة «تفاصيل الشاشة»' in result['reply'] and 'الميزات:' in result['reply']
    assert draft == original and provider.calls == []


def test_generic_details_label_never_guesses_among_multiple_saved_detail_pages():
    data = brief(); data['pages'] = [dict(data['pages'][0], name='تفاصيل الشاشة'), dict(data['pages'][0], name='تفاصيل الطلب')]
    assert project.explanation_page(data, 'تفاصيل المنتج') is None


@pytest.mark.parametrize("value", ["لا توقف المشروع", "لا أريد إلغاء المشروع", "شنو يصير إذا أوقف المشروع؟", "هل ممكن ألغي المشروع؟"])
def test_negated_or_hypothetical_cancellation_keeps_project(value):
    assert not project.cancellation_requested(value)


@pytest.mark.parametrize("value", ["أريد إلغاء المشروع", "وقف المشروع", "الغي طلب التطبيق"])
def test_explicit_cancellation_is_still_supported(value):
    assert project.cancellation_requested(value)


def test_decline_is_not_misread_as_change_instruction(monkeypatch):
    draft = offer(); original = copy.deepcopy(draft)
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: draft)
    monkeypatch.setattr(project, "_invalidate", lambda *args, **kwargs: pytest.fail("Decline must not reprice"))
    provider = FakeProvider({})
    result = project.consult(None, None, "own", "غير موافق", provider=provider, message_id="decline")
    assert result["action"] is None and "ما ثبتنا موافقة" in result["reply"]
    assert draft == original and not provider.calls


def test_scope_builder_receives_ambiguity_to_resolve_before_guessing():
    value = "أريد تطبيق للملاعب والزبون يحجز والمالك يدير الملاعب"
    data = brief(False); data["requirements"] = [{"text": "الحجز", "evidence": value}]
    provider = FakeProvider(data)
    understood = interpretation(value, topic="custom_project", intent="request")
    understood["missingInformation"] = ["هل يقصد عدد الملاعب أو عدد الملاك؟"]
    project.generate_brief(provider, [{"text": value}], None, understanding=understood)
    assert json.loads(provider.calls[0]["user"])["MESSAGE_UNDERSTANDING"] == understood


def test_exact_subrequirement_cannot_keep_an_unrelated_literal_citation():
    value = 'الحجم النافد يبقى ظاهر ومعطل. السلة تحفظ الحجم اللي اختاره الزبون.'
    data = brief()
    data['requirements'] = [{'text': 'السلة تحفظ الحجم اللي اختاره الزبون', 'evidence': 'الحجم النافد يبقى ظاهر ومعطل'}]
    project.ground_literal_requirements(data, [{'text': value}])
    assert data['requirements'][0]['evidence'] == 'السلة تحفظ الحجم اللي اختاره الزبون'


def test_literal_grounding_does_not_invent_evidence_for_a_paraphrase():
    data = brief();row = {'text': 'مخزون متغير مستقل', 'evidence': 'كل حجم إله مخزون'}
    data['requirements'] = [copy.deepcopy(row)]
    project.ground_literal_requirements(data, [{'text': row['evidence']}])
    assert data['requirements'] == [row]


@pytest.mark.parametrize('caption,remaining',[('البيع بالكارتون فقط وكل كارتون بيه 12 حبة للتحويل المخزني','البيع بالكارتون فقط'),('كل كارتون بيه 12 حبة للتحويل المخزني',None)])
def test_per_product_conversion_correction_drops_superseded_fixed_carton_claim(caption,remaining):
    data=brief();data['requirements']=[{'text':caption,'evidence':caption}]
    correction='تصحيح، مو كل الكراتين 12: كل منتج إله عدد حبات بالكارتون يحدده المالك، ما أريد بيع حبة، بس تحويل مخزون حسب المنتج'
    project.ground_unit_conversion(data,[{'text':caption},{'text':correction}])
    assert data['requirements']==([{'text':remaining,'evidence':remaining}] if remaining else [])


def test_conversion_grounding_keeps_a_fixed_factor_without_an_explicit_correction():
    data=brief();data['requirements']=[{'text':'كل كارتون بيه 12 حبة','evidence':'كل كارتون بيه 12 حبة'}]
    original=copy.deepcopy(data)
    project.ground_unit_conversion(data,[{'text':'كل كارتون بيه 12 حبة'}])
    assert data==original


@pytest.mark.parametrize('permission', ['طلب مرتجع وإرساله للموافقة', 'تعديل سعر المنتج', 'إدارة المخزون'])
def test_cashier_sales_and_settlement_only_rejects_extra_operational_permissions(permission):
    value='الكاشير يبيع ويسجل تسديد فقط'
    data=brief();data['requirements']=[{'text':value,'evidence':value}]
    data['roles']=[{'name':'الكاشير','permissions':['إنشاء فواتير البيع', 'تسجيل التسديدات', permission]}]
    assert any('Sales-only cashier' in issue for issue in project.operational_issues(data,[{'text':value}]))
    assert project.repair_fields('Sales-only cashier must not manage returns, products, prices, stock or accounts')=={'roles','pages','workflows'}


@pytest.mark.parametrize('prohibition',['عدم إنشاء المرتجعات','لا يمكن إنشاء المرتجعات','لا يسمح تعديل الأسعار'])
def test_cashier_prohibition_is_not_a_grant_and_owner_return_page_is_valid(prohibition):
    value='الكاشير يبيع ويسجل تسديد فقط'
    data=brief();data['requirements']=[{'text':value,'evidence':value}]
    data['roles']=[{'name':'الكاشير','permissions':['إنشاء فواتير البيع','تسجيل التسديدات',prohibition]}]
    assert not project.operational_issues(data,[{'text':value}])
    data['pages'][0]['name']='المرتجعات';data['pages'][0]['roles']=['الكاشير']
    assert any('Sales-only cashier' in issue for issue in project.operational_issues(data,[{'text':value}]))


def test_certificate_page_rechecks_every_prerequisite_instead_of_only_exam_success():
    value='بعد ما يكمل كل الدروس يفتح الاختبار والشهادة إذا نجح بالاختبار'
    data=brief();data['pages'][0]['name']='الشهادات'
    data['pages'][0]['features']=['عرض الشهادة بعد محاولة الاختبار الناجحة']
    data['pages'][0]['acceptance']=['الطالب ناجح بدرجة 70% أو أكثر']
    assert any('Explicit certificate eligibility' in issue for issue in project.operational_issues(data,[{'text':value}]))
    data['pages'][0]['acceptance'].append('لا تصدر الشهادة إلا بعد اكتمال كل الدروس وتحقيق النجاح بالاختبار')
    assert not project.operational_issues(data,[{'text':value}])


def test_complete_offer_survives_discovery_for_an_unresolved_revision(scoped_requests):
    s, customer, other = scoped_requests
    draft = offer();draft['evidence'] = [{'id':'original','text':REQUEST}]
    project.save(s, customer, 'own', draft)
    original = copy.deepcopy(project.load(s, customer, 'own'))
    value = 'ضيف اختيار اللون داخل صفحة المنتج'
    incomplete = brief(False);incomplete['questions'] = ['أي ألوان متوفرة للمنتج؟']
    provider = FakeProvider(incomplete)
    reply = project.consult(s,customer,'own',value,provider=provider,message_id='pending-color')
    assert 'الخطة الحالية' in reply['reply'] and 'أي ألوان' in reply['reply']
    assert project.load(s,customer,'own') == original and reply['action'] is None
    assert project.pending_evidence(s,customer,'own')[-1]['text'] == value
    assert project.pending_evidence(s,other,'other') == []


def test_grounded_answer_finishes_pending_revision_even_with_existing_offer(scoped_requests):
    s, customer, _ = scoped_requests
    draft=offer();draft['evidence']=[{'id':'original','text':REQUEST}]
    project.save(s,customer,'own',draft)
    project.retain_pending(s,customer,'own',[{'id':'pending','text':'ضيف اختيار اللون داخل صفحة المنتج'}])
    value='الألوان هي الأسود والأبيض'
    provider=FakeProvider(brief())
    reply=project.consult(s,customer,'own',value,provider=provider,message_id='colors',
                          understanding=interpretation(value,intent='request',topic='custom_project'))
    saved=project.load(s,customer,'own')
    assert saved['revision']==5 and saved['brief']['ready'] and saved['customerConsent'] is None
    assert project.pending_evidence(s,customer,'own')==[] and reply['action'] is None
    assert 'ضيف اختيار اللون' in json.dumps(json.loads(provider.calls[0]['user']),ensure_ascii=False)


def test_revision_reply_focuses_on_subfeatures_without_repeating_asked_questions():
    previous={'requirements':[{'text':'النجاح 70%','evidence':'النجاح 70%'}]}
    value='عدل المشاهدة إلى 90%، النجاح 70% يبقى مثل ما هو'
    current={'requirements':[{'text':'النجاح 70%','evidence':'النجاح 70%'},{'text':'عدل المشاهدة إلى 90%','evidence':'عدل المشاهدة إلى 90%'}]}
    reply=project.changed_requirement_reply(current,previous,value,applied=True)
    assert '90%' in reply and 'النجاح 70%' not in reply
    question='التسجيل برقم لو إيميل؟'
    assert project.unanswered_questions([question],[{'role':'finora','text':question}])==[]


def test_answered_actor_question_cannot_be_saved_as_missing_information():
    value = "أريد موقع للمطعم، صاحب المطعم يدير القائمة والمطبخ يشوف الطلبات والمندوب يوصل"
    data = brief(False); data["requirements"] = [{"text": "طلبات", "evidence": value}]
    data["questions"] = ["منو راح يستخدم الموقع؟"]
    with pytest.raises(ValueError, match="Repeated audience question"):
        project.validate_brief(data, [{"text": value}])


def test_semantic_new_platform_request_enters_consultation_without_creating_account(monkeypatch):
    value = "ممكن تبنيلي بوابة لدروسنا؟"
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: None)
    monkeypatch.setattr(project, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(project, "_invalidate", lambda *args, **kwargs: None)
    generated = brief(False)
    generated["requirements"] = [{"text": "بوابة دروس", "evidence": value}]
    provider = FakeProvider(generated)
    data = interpretation(value, intent="request", topic="custom_project")
    assert project.active(None, None, "own", value, understanding=data)
    result = project.consult(None, None, "own", value, provider=provider, message_id="new", understanding=data)
    assert result and result["action"] is None
    assert not project.semantic_project_request(interpretation(value, confidence=.5, intent="request", topic="custom_project"))
    assert not project.semantic_project_request(interpretation(value, intent="question", topic="custom_project"))


def test_restaurant_explicit_users_are_not_erased_by_audience_gate():
    value = "أريد موقع طلبات لمطعم. صاحب المطعم يدير القائمة والمطبخ يشوف التحضير فقط والمندوب طلباته."
    data = brief(); data["requirements"] = [{"text": "طلبات المطعم", "evidence": value}]
    parsed = project.validate_brief(data, [{"text": value}], require_workflows=True)
    assert parsed["ready"] and parsed["questions"] == [] and parsed["pages"]


def test_clinic_explicit_files_appointments_and_payments_are_known_workflow():
    value = "أريد نظام ويب خاص لعيادة أسنان بطبيب واحد واستقبال واحد. ملفات المرضى والمواعيد وخطة العلاج والجلسات والمدفوعات."
    data = brief(); data["requirements"] = [{"text": "ملفات المرضى والمواعيد", "evidence": value}]
    parsed = project.validate_brief(data, [{"text": value}], require_workflows=True)
    assert parsed["ready"] and parsed["questions"] == [] and parsed["pages"]


@pytest.mark.parametrize("clinical_page", ["المرضى", "ملف المريض", "خطة العلاج", "صور العلاج", "تفاصيل الجلسة"])
def test_reception_only_scope_cannot_expose_clinical_pages_even_with_read_only_acceptance(clinical_page):
    data = brief(); data["roles"] = [{"name": "الطبيب", "permissions": []}, {"name": "الاستقبال", "permissions": []}]
    page = copy.deepcopy(data["pages"][0]); page.update(name=clinical_page, roles=["الطبيب", "الاستقبال"], acceptance=["الاستقبال لا يستطيع تعديل المحتوى السريري"])
    data["pages"] = [page]
    evidence = [{"text": "الاستقبال يشوف المواعيد والقبض فقط والطبيب يشوف الملف والعلاج"}, {"text": "الحجز من الاستقبال فقط، وصور العلاج للطبيب فقط"}]
    assert any("reception-only" in issue for issue in project.operational_issues(data, evidence))
    page["roles"] = ["الطبيب"]
    assert not any("reception-only" in issue for issue in project.operational_issues(data, evidence))


def test_complete_technical_scope_does_not_need_a_price_to_be_ready():
    data = brief(); data["estimate"] = None
    parsed = project.validate_brief(data, [{"text": REQUEST}], require_workflows=True)
    assert parsed["ready"] and parsed["questions"] == [] and parsed["workflows"]


@pytest.mark.parametrize("terms", [None, {"amount": 0, "currency": "IQD", "days": 30, "mvpDays": 10}])
def test_unpriced_or_invalid_offer_cannot_be_published(monkeypatch, terms):
    from modules.finora_core.brain.tools import ToolError
    draft = offer(); draft.update(phase="internal_review", scopeConsent="delivered-scope", terms=terms,
                                  evidence=[{"text": REQUEST}], quoteHash=None)
    draft["brief"]["estimate"] = None
    original = copy.deepcopy(draft)
    monkeypatch.setattr(project, "load", lambda *args, **kwargs: draft)
    monkeypatch.setattr(project, "save", lambda *args, **kwargs: pytest.fail("Invalid terms must not be saved"))
    args = project.approval_args(None, None, {"type": "publish_project_quote", "conversation_ref": "own", "revision": 4})
    with pytest.raises(ToolError, match="أدخل سعراً"):
        project.apply(None, None, args)
    assert draft == original


class StagedProvider(FakeProvider):
    supports_staged_projects = True


def stages(data):
    # Staged extraction records literal customer clauses; prose belongs in the specification.
    for row in data['requirements']:
        row['text']=row['evidence']
    discovery_fields = {"title", "kind", "goal", "audience", "platforms", "requirements", "suggestions", "questions", "ready"}
    return ({key: copy.deepcopy(value) for key, value in data.items() if key in discovery_fields},
            {key: copy.deepcopy(value) for key, value in data.items() if key not in discovery_fields and key != "workflows"})


def test_staged_literal_requirement_caption_repairs_wrong_clause_binding():
    value='المقاس النافد مو نخفيه، خليه يبين بس معطل. إذا بدّل اللون ينمسح المقاس القديم.'
    expected=brief()
    expected['requirements']=[{'text':'خليه يبين بس معطل','evidence':'إذا بدّل اللون ينمسح المقاس القديم'}]
    discovery_fields={'title','kind','goal','audience','platforms','requirements','suggestions','questions','ready'}
    discovery={k:copy.deepcopy(v) for k,v in expected.items() if k in discovery_fields}
    scope={k:copy.deepcopy(v) for k,v in expected.items() if k not in discovery_fields and k!='workflows'}
    provider=StagedProvider(discovery,scope,{'workflows':expected['workflows']})
    parsed,_=project.generate_brief(provider,[{'text':value}],None)
    assert parsed['requirements']==[{'text':'خليه يبين بس معطل','evidence':'خليه يبين بس معطل'}]


def test_staged_plan_preserves_specification_and_validates_graph_with_total_usage():
    expected = brief(); discovery, scope = stages(expected)
    provider = StagedProvider(discovery, scope, {"workflows": copy.deepcopy(expected["workflows"])})
    data, usage = project.generate_brief(provider, [{"text": REQUEST}], None)
    assert data == expected and len(provider.calls) == 3
    assert usage.input_tokens == 360 and usage.output_tokens == 120
    flow_payload = json.loads(provider.calls[2]["user"])
    assert flow_payload["SCOPE"]["pages"] == expected["pages"]
    assert flow_payload["SCOPE"]["roles"] == expected["roles"]


def test_staged_discovery_does_not_generate_a_speculative_graph():
    data = brief(False)
    for key in ("pages", "roles", "entities", "integrations", "milestones", "workflows"):
        data[key] = []
    data["estimate"] = None
    provider = StagedProvider(stages(data)[0])
    parsed, _ = project.generate_brief(provider, [{"text": REQUEST}], None)
    assert not parsed["ready"] and parsed["workflows"] == [] and len(provider.calls) == 1


def test_requested_plan_reviews_discovery_before_optional_questions_block_it():
    expected = brief(); discovery, scope = stages(expected)
    incomplete = copy.deepcopy(discovery)
    incomplete.update(ready=False, questions=["هل تريد تقارير أو إشعارات؟"])
    provider = StagedProvider(incomplete, discovery, scope, {"workflows": expected["workflows"]})
    data, usage = project.generate_brief(provider, [{"text": REQUEST}, {"text": "كمل الخطة الفنية"}], None)
    assert data == expected and len(provider.calls) == 4 and usage.input_tokens == 480
    assert "STAGE: review discovery" in provider.calls[1]["system"]
    assert json.loads(provider.calls[1]["user"])["DISCOVERY_TO_REVIEW"]["questions"] == incomplete["questions"]


def test_discovery_review_keeps_genuinely_missing_requirements_unresolved():
    data = brief(False); discovery, _ = stages(data)
    provider = StagedProvider(discovery, discovery)
    parsed, _ = project.generate_brief(provider, [{"text": REQUEST}, {"text": "كمل الخطة"}], None)
    assert not parsed["ready"] and parsed["questions"] == data["questions"]
    assert len(provider.calls) == 2 and parsed["pages"] == []


def test_ambiguous_discovery_does_not_announce_a_guessed_business(scoped_requests):
    s, customer, _ = scoped_requests
    value = "أريد موقع بيع أجهزة كهربائية للموبايل والكمبيوتر"
    data = brief(False)
    data.update(goal="متجر بيع الموبايل والكمبيوتر", questions=["تقصد أنواع الأجهزة لو شاشات الموقع؟"], suggestions=[])
    data["requirements"] = [{"text": "موقع بيع", "evidence": value}]
    understood = interpretation(value, intent="request", topic="custom_project")
    understood["missingInformation"] = ["معنى الموبايل والكمبيوتر غير واضح"]
    result = project.consult(s, customer, "own", value, provider=FakeProvider(data), message_id="ambiguous", understanding=understood)
    assert result["reply"] == data["questions"][0] and result["action"] is None


def test_staged_invalid_edge_gets_repaired_instead_of_being_saved():
    expected = brief(); broken = copy.deepcopy(expected["workflows"])
    broken[0]["steps"][0]["next"][0]["stepId"] = "undefined"
    discovery, scope = stages(expected)
    provider = StagedProvider(discovery, scope, {"workflows": broken}, {"workflows": copy.deepcopy(expected["workflows"])})
    data, usage = project.generate_brief(provider, [{"text": REQUEST}], None)
    assert data == expected and len(provider.calls) == 4 and usage.input_tokens == 480
    repair = json.loads(provider.calls[-1]["user"])
    assert repair["REPLACE_ONLY_FIELDS"] == ["workflows"] and repair["WORKFLOWS_TO_REPLACE"] == ["reserve"]


def test_workflow_repair_cannot_invent_a_combined_or_higher_role():
    class RecordingProvider(StagedProvider):
        def generate_structured(self, **kwargs):
            self.last_schema = kwargs["schema"]
            return super().generate_structured(**kwargs)
    expected = brief(); broken = copy.deepcopy(expected["workflows"])
    broken[0]["steps"][0]["next"][0]["stepId"] = "undefined"
    discovery, scope = stages(expected)
    provider = RecordingProvider(discovery, scope, {"workflows": broken}, {"workflows": copy.deepcopy(expected["workflows"])})
    data, _ = project.generate_brief(provider, [{"text": REQUEST}], None)
    role_schema = provider.last_schema["properties"]["workflows"]["items"]["properties"]["steps"]["items"]["properties"]["role"]
    assert role_schema["enum"] == sorted(role["name"] for role in expected["roles"])
    assert data == expected


def test_missing_workflows_can_be_added_without_overwriting_healthy_flows_or_restarting_discovery():
    expected = brief()
    first = copy.deepcopy(expected["workflows"][0])
    expected["workflows"] = [{**copy.deepcopy(first), "id": f"operation_{i}"} for i in range(8)]
    page = copy.deepcopy(expected["pages"][0]); page["id"] = "extra"; page["name"] = "إدارة إضافية"
    page["roles"] = sorted({step["role"] for step in first["steps"]})
    expected["pages"].append(page)
    missing = copy.deepcopy(first); missing["id"] = "extra_flow"
    for step in missing["steps"]: step["pageId"] = "extra"
    discovery, scope = stages(expected)
    repeated = copy.deepcopy(expected["workflows"][0]); repeated["name"] = "تغيير غير مطلوب لمسار سليم"
    provider = StagedProvider(discovery, scope, {"workflows": expected["workflows"]}, {"workflows": [repeated, missing]})
    data, _ = project.generate_brief(provider, [{"text": REQUEST}], None)
    assert len(data["workflows"]) == 9 and data["workflows"][0] == expected["workflows"][0]
    assert len(provider.calls) == 4 and "REPLACE_ONLY_FIELDS" in json.loads(provider.calls[-1]["user"])


def test_schema_failure_in_a_graph_does_not_restart_unrelated_discovery():
    assert project.repair_fields("Schema mismatch at workflows/2/steps/0/role: enum") == {"workflows"}
    assert project.repair_fields("Schema mismatch at entities/1/relatedTo: type") == {"entities"}


def test_workflow_timeout_reuses_completed_specification_without_regenerating_it():
    expected = brief(); discovery, scope = stages(expected)
    provider = StagedProvider(discovery, scope, ProviderError("timeout", "flow unavailable"),
                              {"workflows": copy.deepcopy(expected["workflows"])})
    data, usage = project.generate_brief(provider, [{"text": REQUEST}], None)
    assert data == expected and len(provider.calls) == 4 and usage.input_tokens == 360
    retry = json.loads(provider.calls[-1]["user"])
    assert retry["REPLACE_ONLY_FIELDS"] == ["workflows"]
    assert retry["UNTRUSTED_DRAFT_TO_REPAIR"]["pages"] == expected["pages"]
    assert retry["UNTRUSTED_DRAFT_TO_REPAIR"]["roles"] == expected["roles"]


def test_project_retry_stops_when_wall_clock_budget_exhausted(monkeypatch):
    clock = [0]
    monkeypatch.setattr(project.time, "monotonic", lambda: clock[0])
    def advance():
        clock[0] += 161
    provider = FakeProvider(ProviderError("timeout", "unavailable"), on_call=advance)
    with pytest.raises(ProviderError, match="budget exhausted"):
        project.generate_brief(provider, [{"text": REQUEST}], None)
    assert len(provider.calls) == 1


def test_core_calls_disable_sdk_retry_without_changing_shared_client(monkeypatch):
    from modules.ai_sales import openai_service
    calls = []
    shared = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(("shared", kw))))
    scoped = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(("scoped", kw))))
    options = []
    shared.with_options = lambda **kw: options.append(kw) or scoped
    monkeypatch.setattr(openai_service, "get_openai_client", lambda **kw: shared)
    openai_service.create_response(model="test", max_retries=0, timeout=20)
    openai_service.create_response(model="test", timeout=20)
    assert options == [{"max_retries": 0}]
    assert [row[0] for row in calls] == ["scoped", "shared"]
    assert all("max_retries" not in row[1] for row in calls)


def test_insurance_deduction_question_is_not_quote_negotiation():
    value = "إذا رجعت المعدة متضررة، يكدر الموظف يخصم من التأمين من كيفه؟"
    assert project.negotiate(None, None, "own", offer(), value, "deduction", "", shadow=True,
                             understanding=interpretation(value, topic="custom_project")) is None
    assert project.negotiate(None, None, "own", offer(), value, "deduction", "", shadow=True) is None


@pytest.mark.parametrize("permission, rejected", [
    ("عدم الوصول إلى إدارة المنتجات أو الأسعار أو المخزون", False),
    ("تعديل الأسعار", True),
    ("عدم تعديل المنتجات لكن يسمح تعديل الأسعار", True),
])
def test_permission_prohibitions_are_not_confused_with_grants(permission, rejected):
    data = brief()
    data["roles"].append({"name": "موظف", "permissions": ["عرض الطلبات", permission]})
    evidence = [{"text": "الموظف يجهز الطلبات فقط"}]
    issues = project.operational_issues(data, evidence)
    assert any("Order-only staff must not edit" in issue for issue in issues) == rejected


def test_complete_plan_instruction_during_discovery_is_not_swallowed_as_advice(scoped_requests):
    s, customer, _ = scoped_requests
    draft = offer(); draft.update(brief=brief(False), phase="discovery", evidence=[{"id": "original", "text": REQUEST}])
    project.save(s, customer, "own", draft)
    provider = FakeProvider(brief())
    result = project.consult(s, customer, "own", "كمل الخطة الفنية، التفاصيل البسيطة اقترحها للمراجعة", provider=provider, message_id="complete",
                             understanding=interpretation("كمل الخطة الفنية، التفاصيل البسيطة اقترحها للمراجعة", intent="request", topic="custom_project"))
    saved = project.load(s, customer, "own")
    assert saved["phase"] == "scope_review" and saved["brief"]["ready"] and result["action"] is None
    assert "CUSTOMER_MESSAGES" in json.loads(provider.calls[0]["user"])


def test_advice_is_reviewed_with_literal_scope_and_never_changes_an_offer():
    class ReviewedProvider(FakeProvider):
        supports_advice_review = True
    draft = offer(); original = copy.deepcopy(draft)
    provider = ReviewedProvider({"answer": "إضافة فاصل تتيح الحجز المتداخل", "questions": []},
                                {"answer": "لا، الساعة من 10 إلى 11 مشغولة؛ الفاصل يزيد الفترة ولا يتيح 10:30.", "questions": []})
    reply, usage = project.discuss(provider, draft, "أريد تفسير منع تداخل المواعيد وصلاحيات الموظفة")
    assert reply == "لا، الساعة من 10 إلى 11 مشغولة؛ الفاصل يزيد الفترة ولا يتيح 10:30."
    assert draft == original and usage.input_tokens == 240
    assert json.loads(provider.calls[1]["user"])["PROPOSED_ADVICE"]["answer"] == "إضافة فاصل تتيح الحجز المتداخل"
    assert "restricted staff" in provider.calls[1]["system"]


def test_unavailable_advice_review_does_not_send_unverified_advice():
    class ReviewedProvider(FakeProvider):
        supports_advice_review = True
    draft = offer(); original = copy.deepcopy(draft)
    provider = ReviewedProvider({"answer": "نصيحة غير مراجعة", "questions": []}, ProviderError("timeout", "review unavailable"))
    with pytest.raises(ProviderError):
        project.discuss(provider, draft, "شلون أحمي الحسابات؟")
    assert draft == original


@pytest.mark.parametrize("question, end", [
    ("الخدمة ساعة، إذا حجزت 10 يصير ثانية تحجز 10 ونص عند نفس الموظفة؟", "11:00"),
    ("خدمة مدتها ساعة تبدأ 10 عند نفس الموظفة. إذا خليت فاصل 15 دقيقة بعدها، يصير أقبل حجز 10 ونص؟", "11:15"),
])
def test_booking_arithmetic_cannot_recommend_an_overlapping_alternative(question, end):
    provider = FakeProvider({})
    draft = offer(); original = copy.deepcopy(draft)
    reply, usage = project.discuss(provider, draft, question)
    assert end in reply and "10:30" in reply and "عملية واحدة" in reply
    assert draft == original and not provider.calls and usage.input_tokens == 0


@pytest.mark.parametrize("question", [
    "الخدمة ساعة تبدأ 10؛ حجز 10 ونص لنفس الموظفة وشنو صلاحياتها؟",
    "الخدمة نص ساعة تبدأ 10، حجز 10 ونص لنفس الموظفة؟",
    "خدمة مدتها ساعة تبدأ 10؛ حجز 10 ونص عند موظفة ثانية؟",
])
def test_booking_arithmetic_does_not_guess_other_durations_or_swallow_extra_questions(question):
    assert project.appointment_overlap_answer(question) is None


@pytest.fixture
def scoped_requests(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from modules.finora_core.models import FcSetting
    from modules.finora_core.brain.models import FcCustomer, FcConversationCustomer
    from modules.finora_core.brain import support
    engine = create_engine("sqlite:///:memory:")
    for model in (FcCustomer, FcConversationCustomer, FcSetting):
        model.__table__.create(engine)
    monkeypatch.setattr(support, "report", lambda *args, **kwargs: None)
    monkeypatch.setattr(project, "_invalidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(project, "emit", lambda *args, **kwargs: None)
    with Session(engine) as s:
        customer = FcCustomer(display_name="عميل الاختبار"); other = FcCustomer(display_name="العميل الآخر")
        s.add_all([customer, other]); s.flush()
        s.add_all([FcConversationCustomer(conversation_ref="own", customer_id=customer.id),
                   FcConversationCustomer(conversation_ref="other", customer_id=other.id)])
        s.flush()
        yield s, customer, other
    engine.dispose()


def test_failed_initial_plan_retains_literal_own_request_and_can_answer_followup(scoped_requests):
    s, customer, other = scoped_requests
    result = project.consult(s, customer, "own", REQUEST, provider=FakeProvider(ProviderError("insufficient_quota", "unavailable")), message_id="first")
    assert result["action"] is None and project.load(s, customer, "own") is None
    assert project.pending_evidence(s, customer, "own") == [{"id": "first", "text": REQUEST}]
    assert project.pending_evidence(s, other, "other") == []
    with pytest.raises(Exception, match="الاستشارة تخص"):
        project.pending_evidence(s, other, "own")
    value = "إخفاء الصفحة وحده يكفي للحماية؟"
    provider = FakeProvider({"answer": "لا، لازم تحقق الصلاحية وملكية الملعب بالسيرفر عند كل طلب.", "questions": []})
    answer = project.consult(s, customer, "own", value, provider=provider, message_id="followup",
                             understanding=interpretation(value, topic="custom_project"))
    assert "بالسيرفر" in answer["reply"] and answer["action"] is None
    assert REQUEST in json.loads(provider.calls[0]["user"])["UNTRUSTED_SCOPE"]["goal"]
    assert project.load(s, customer, "own") is None


def test_retry_uses_retained_requirements_without_claiming_approval(scoped_requests):
    s, customer, _ = scoped_requests
    project.retain_pending(s, customer, "own", [{"id": "first", "text": REQUEST}])
    provider = FakeProvider(brief())
    reply = project.consult(s, customer, "own", "كمل نفس المتطلبات", provider=provider, message_id="retry")
    assert reply["action"] is None and project.pending_evidence(s, customer, "own") == []
    draft = project.load(s, customer, "own")
    assert draft["brief"]["ready"] and draft["customerConsent"] is None and not draft["depositVerified"]
    assert REQUEST in json.dumps(json.loads(provider.calls[0]["user"])["CUSTOMER_MESSAGES"], ensure_ascii=False)


def test_failed_revision_keeps_latest_request_separate_from_the_validated_offer(scoped_requests):
    s, customer, _ = scoped_requests
    draft = offer(); draft["evidence"] = [{"id": "original", "text": REQUEST}]
    project.save(s, customer, "own", draft)
    original = copy.deepcopy(project.load(s, customer, "own"))
    value = "ضيف صفحة جديدة لتقارير المالك فقط"
    project.consult(s, customer, "own", value, provider=FakeProvider(ProviderError("insufficient_quota", "unavailable")), message_id="change")
    assert project.load(s, customer, "own") == original
    assert project.pending_evidence(s, customer, "own")[-1] == {"id": "change", "text": value}
    provider = FakeProvider(brief())
    project.consult(s, customer, "own", "عدل الخطة حسب طلبي الأخير", provider=provider, message_id="retry")
    assert value in json.dumps(json.loads(provider.calls[0]["user"])["CUSTOMER_MESSAGES"], ensure_ascii=False)
    assert project.pending_evidence(s, customer, "own") == []


def test_keep_existing_offer_discards_unapplied_change_without_changing_offer(scoped_requests):
    s, customer, _ = scoped_requests
    draft = offer(); project.save(s, customer, "own", draft)
    project.retain_pending(s, customer, "own", [{"id": "change", "text": "ضيف دفع إلكتروني"}])
    provider = FakeProvider({})
    project.consult(s, customer, "own", "لا تغير شي", provider=provider, message_id="keep")
    assert project.load(s, customer, "own") == draft and project.pending_evidence(s, customer, "own") == []
    assert not provider.calls


def test_shadow_failure_does_not_retain_requests_or_change_plan(scoped_requests):
    s, customer, _ = scoped_requests
    project.consult(s, customer, "own", REQUEST, provider=FakeProvider(ProviderError("insufficient_quota", "unavailable")), message_id="shadow", shadow=True)
    assert project.pending_evidence(s, customer, "own") == [] and project.load(s, customer, "own") is None
