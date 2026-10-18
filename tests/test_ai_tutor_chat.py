"""AI Tutor chat: Iraqi-Arabic intent resolution, registry-only answers, privacy, fallback, API."""
import json
from pathlib import Path

import pytest

from modules.ai_tutor import registry
from modules.ai_tutor.chat import context as chat_context
from modules.ai_tutor.chat import intent as intents
from modules.ai_tutor.chat import knowledge as kb_mod
from modules.ai_tutor.chat import privacy, ratelimit, service
from modules.ai_tutor.chat.provider import NullProvider, ProviderError, TutorAIProvider
from tests.test_ai_tutor_backend import BASE, _create_doctor, _enable, _user, tutor_app  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]


def ctx(**over):
    base = {
        "page": "dashboard", "route": "/clinics", "user_role": "admin", "permissions": [],
        "available_tutorials": {"doctor.create", "specialty.create"},
        "runnable_tutorials": {"doctor.create", "specialty.create"},
        "unavailable_reasons": {},
        "active_tutorial": None, "issue": None, "facts": {"doctors_count": 1, "specialties_count": 1},
    }
    base.update(over)
    return base


class FakeProvider(TutorAIProvider):
    name = "fake"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def classify_intent(self, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.answer


# ------------------------------------------------------------ intent: Iraqi Arabic

@pytest.mark.parametrize("phrase", [
    "شلون أضيف طبيب؟", "شلوت اضيف دكتور", "علمني أضيف دكتور", "اريد ادخل دكتور جديد", "أريد أضيف طبيب",
    "اسوي حساب دكتور", "دكتور جديد", "اضيف دكتر", "وين اضيف طبيب", "كيف اضيف طبيب جديد للعيادة", "اريد اسجل طبيب", "طبيب جديد",
])
def test_doctor_create_phrasings(phrase):
    res = intents.resolve(phrase)
    assert res.intent == "doctor.create" and res.confidence >= intents.CONFIDENT, phrase


@pytest.mark.parametrize("phrase", [
    "وين أضيف اختصاص؟", "اريد اسوي تخصص", "اريد اضيف اختصاص", "تخصص جديد", "اختصاص جديد", "شلون اضيف تخصص", "أريد أضيف اختصاص جديد",
])
def test_specialty_create_phrasings(phrase):
    assert intents.resolve(phrase).intent == "specialty.create", phrase


def test_other_registered_features():
    assert intents.resolve("أريد أسوي موعد").intent == "appointment.create"
    assert intents.resolve("وين أضيف زبون").intent == "patient.create"
    assert intents.resolve("وين الصلاحيات؟").intent == "permissions.manage"
    assert intents.resolve("شلون اضيف موظف").intent == "employee.create"


def test_modes_follow_the_question_word():
    assert intents.resolve("شلون أضيف طبيب؟").mode == "guide"
    assert intents.resolve("وين أضيف اختصاص؟").mode == "show_me"
    assert intents.resolve("وريني وين اضيف دكتور").mode == "show_me"
    assert intents.resolve("شنو اضافة دكتور").mode == "explain"


def test_exact_alias_source_and_typo_tolerance():
    assert intents.resolve("اسوي حساب دكتور").source == "exact"
    assert intents.resolve("اضيف دكتر").intent == "doctor.create"  # typo snaps to the vocabulary


def test_meta_intents():
    assert intents.resolve("شنو هاي الصفحة؟").intent == intents.META_PAGE
    assert intents.resolve("شلون أستخدم هاي الصفحة؟").intent == intents.META_PAGE
    assert intents.resolve("شنو اسوي هسه؟").intent == intents.META_ACTIVE_HELP
    assert intents.resolve("ليش ما يكمل؟").intent == intents.META_ACTIVE_WHY
    assert intents.resolve("شنو علاج هذا المريض").intent == intents.META_MEDICAL
    assert intents.resolve("هلا").intent == intents.META_GREETING


def test_ambiguity_and_low_confidence_never_guess():
    amb = intents.resolve("أريد أضيف حساب")
    assert amb.intent is None and amb.confidence >= intents.CLARIFY
    assert {c for c, _ in amb.candidates[:2]} == {"doctor.create", "employee.create"}
    for phrase in ("وين العمليات الجراحية", "وين نظام العمليات الجراحية", "شنو هذا", "xyz", "اريد ارسل رسالة واتساب للمريض"):
        res = intents.resolve(phrase)
        assert res.intent is None and res.confidence < intents.CLARIFY, phrase


# ----------------------------------------------------------- responses (no AI)

def test_tutorial_suggestion_contract():
    r = service.answer("شلون أضيف طبيب", ctx())
    assert r["type"] == "tutorial_suggestion" and r["tutorial_id"] == "doctor.create"
    assert "أكدر أعلمك إضافة طبيب" in r["message"]
    assert r["actions"][0] == {"type": "start_tutorial", "label": "ابدأ التعليم", "tutorial_id": "doctor.create"}
    assert any(a["type"] == "show_me" for a in r["actions"])


def test_explain_mode_does_not_start_and_offers_practical_lesson():
    r = service.answer("شنو اضافة دكتور", ctx())
    assert r["type"] == "explanation"
    assert [a["label"] for a in r["actions"] if a["type"] == "start_tutorial"] == ["علمني عملياً"]


def test_feature_without_tutorial_gets_limited_registry_explanation():
    r = service.answer("أريد أسوي موعد", ctx())
    assert r["type"] == "explanation" and r["tutorial_id"] is None
    assert "الميزة موجودة بالنظام، لكن الشرح التفاعلي الخاص بها بعده غير متوفر" in r["message"]
    assert not any(a["type"] == "start_tutorial" for a in r["actions"])
    show = next(a for a in r["actions"] if a["type"] == "show_me")
    assert show["target"] == {"action": "nav.appointments"}  # visual guidance to the real sidebar item


def test_show_me_targets_the_page_control_when_already_there():
    r = service.answer("وين أضيف اختصاص؟", ctx(page="specialties"))
    show = next(a for a in r["actions"] if a["type"] == "show_me")
    assert show["target"] == {"action": "specialty.create"} and show["reveal"] == []
    r = service.answer("وين أضيف اختصاص؟", ctx(page="dashboard"))
    show = next(a for a in r["actions"] if a["type"] == "show_me")
    assert show["target"] == {"action": "nav.specialties"} and {"action": "nav.menu.open"} in show["reveal"]


def test_page_explanation_comes_from_the_registry():
    r = service.answer("شنو هاي الصفحة؟", ctx(page="staff"))
    assert "أنت حالياً بصفحة" in r["message"]
    assert "تدير الأطباء والموظفين وحسابات الدخول والصلاحيات" in r["message"]
    assert {a["tutorial_id"] for a in r["actions"] if a["type"] == "start_tutorial"} == {"doctor.create"}
    assert "ما كدرت أحدد الصفحة" in service.answer("شنو هاي الصفحة؟", ctx(page=None))["message"]


def test_clarification_buttons_and_follow_up():
    r = service.answer("أريد أضيف حساب", ctx())
    assert r["type"] == "clarification" and r["message"] == "تقصد طبيب لو موظف؟"
    assert [a["label"] for a in r["actions"]] == ["طبيب", "موظف"]
    follow = service.answer("", ctx(), forced_intent=r["actions"][0]["intent"])
    assert follow["type"] == "tutorial_suggestion" and follow["tutorial_id"] == "doctor.create"
    assert service.answer("", ctx(), forced_intent="surgery.manage")["type"] == "error"


def test_unknown_feature_is_not_found_without_invention():
    r = service.answer("وين نظام العمليات الجراحية", ctx())
    assert r["type"] == "not_found" and "ما لقيت هذه الميزة ضمن النسخة الحالية" in r["message"]
    assert all(a["tutorial_id"] in {"doctor.create", "specialty.create"} for a in r["actions"] if a["type"] == "start_tutorial")
    assert "جراح" not in " ".join(a["label"] for a in r["actions"])


def test_medical_advice_is_refused_but_locations_are_explained():
    r = service.answer("شنو علاج هذا المريض", ctx())
    assert "ما أكدر أعطي تشخيص أو علاج" in r["message"] and "Finora" in r["message"]
    where = service.answer("وين اسجل التشخيص", ctx())
    assert "المعاينة الطبية" in where["message"]


def test_active_tutorial_help_explains_only_the_current_step():
    active = {"id": "doctor.create", "step_id": "name", "step_index": 5}
    r = service.answer("شنو اسوي هسه", ctx(active_tutorial=active))
    assert r["message"].startswith("هسه:") and "الاسم الكامل" in r["message"]
    assert "اضغط" not in r["message"]  # no replay of earlier steps
    assert service.answer("شنو اسوي هسه", ctx())["message"].startswith("ماكو درس شغال")


def test_error_help_uses_the_current_state():
    active = {"id": "doctor.create", "step_id": "name", "step_index": 5}
    facts = {"doctors_count": 1, "specialties_count": 0}
    r = service.answer("ليش ما يكمل", ctx(active_tutorial=active, issue="dependency_missing", facts=facts))
    assert "قبل إضافة الطبيب نحتاج نضيف اختصاص" in r["message"]
    assert [a["type"] for a in r["actions"]] == ["resume_dependency"]
    # A claimed dependency problem is ignored when the facts say it is fine.
    ok = service.answer("ليش ما يكمل", ctx(active_tutorial=active, issue="dependency_missing"))
    assert not any(a["type"] == "resume_dependency" for a in ok["actions"])
    assert "العنصر المطلوب" in service.answer("ليش ما يكمل", ctx(active_tutorial=active, issue="target_missing"))["message"]
    assert "الحفظ ما نجح" in service.answer("ليش ما يكمل", ctx(active_tutorial=active, issue="validation_failed"))["message"]


def test_permission_filtering_hides_the_lesson():
    r = service.answer("شلون أضيف طبيب", ctx(available_tutorials=set(), unavailable_reasons={"doctor.create": "permission"}))
    assert r["type"] == "explanation" and "صلاحية" in r["message"]
    assert not any(a["type"] == "start_tutorial" for a in r["actions"])


def test_availability_filtering_explains_why_without_offering_the_lesson():
    """A lesson that exists but is unavailable for a non-permission reason (e.g. the tenant's specialty) gets its own
    honest message — never the generic "no permission" text, and never a start_tutorial action."""
    r = service.answer("شلون اسوي خطة علاج", ctx(
        available_tutorials=set(), runnable_tutorials={"treatment_plan.create"},
        unavailable_reasons={"treatment_plan.create": "specialty:dentistry"}))
    assert r["type"] == "explanation"
    assert "عيادات الأسنان" in r["message"]
    assert "صلاحية" not in r["message"]
    assert not any(a["type"] == "start_tutorial" for a in r["actions"])


# ---------------------------------------------------------- provider + privacy

def test_clear_intent_never_calls_the_provider():
    provider = FakeProvider({"intent": "specialty.create", "confidence": 0.99})
    r = service.answer("شلون أضيف طبيب", ctx(), provider=provider)
    assert provider.calls == [] and r["tutorial_id"] == "doctor.create"


def test_provider_helps_only_when_the_message_is_unclear():
    provider = FakeProvider({"intent": "doctor.create", "confidence": 0.9})
    r = service.answer("ابي ازيد اخصائي جديد عندنا", ctx(), provider=provider)
    assert len(provider.calls) == 1 and r["tutorial_id"] == "doctor.create" and r["meta"]["source"] == "ai"


def test_provider_failure_falls_back_to_deterministic_answers():
    provider = FakeProvider(error=ProviderError("timeout"))
    assert service.answer("وين نظام العمليات الجراحية", ctx(), provider=provider)["type"] == "not_found"
    assert service.answer("أريد أضيف حساب", ctx(), provider=provider)["type"] == "clarification"
    assert service.answer("شلون أضيف طبيب", ctx(), provider=provider)["type"] == "tutorial_suggestion"


def test_provider_cannot_invent_intents_or_low_confidence_matches():
    for answer in ({"intent": "surgery.manage", "confidence": 0.99}, {"intent": "doctor.create", "confidence": 0.2},
                   {"intent": "doctor.create", "confidence": "high"}, ["not", "a", "dict"], None):
        r = service.answer("وين نظام العمليات الجراحية", ctx(), provider=FakeProvider(answer))
        assert r["type"] == "not_found", answer


def test_provider_candidates_become_a_clarification_of_known_intents_only():
    provider = FakeProvider({"intent": None, "confidence": 0.7, "candidates": ["doctor.create", "bogus", "employee.create"]})
    r = service.answer("ابي حساب جديد للمركز الطبي", ctx(), provider=provider)
    assert r["type"] == "clarification" and {a["intent"] for a in r["actions"]} == {"doctor.create", "employee.create"}


def test_patient_and_clinical_messages_never_reach_the_provider():
    provider = FakeProvider({"intent": "doctor.create", "confidence": 0.9})
    for text in ("اريد اسجل المريض احمد محمد هاتفه 07701234567", "شنو علاج هذا المريض", "وين اسجل تشخيص السيد علي"):
        service.answer(text, ctx(), provider=provider)
    assert provider.calls == []


def test_payload_is_sanitised_and_contains_registry_data_only():
    provider = FakeProvider(None)
    service.answer("ابي ازيد اخصائي رقمه 07701234567 بريده a.b@clinic.iq", ctx(), provider=provider)
    payload = json.dumps(provider.calls[0], ensure_ascii=False)
    assert "07701234567" not in payload and "a.b@clinic.iq" not in payload and "[رقم]" in payload
    assert set(provider.calls[0]) == {"message", "page", "active_tutorial", "intents"}
    assert privacy.redact("x" * 1000).__len__() == privacy.MAX_LLM_CHARS


def test_null_provider_is_the_default_and_never_required():
    assert NullProvider().classify_intent({}) is None
    assert service.answer("شلون أضيف طبيب", ctx(), provider=None)["type"] == "tutorial_suggestion"


def test_response_validator_strips_html_and_drops_invented_actions():
    kb = kb_mod.load()
    raw = {
        "type": "explanation", "message": "<b>مرحبا</b> <script>alert(1)</script> نص", "tutorial_id": "ghost.tutorial",
        "actions": [
            {"type": "start_tutorial", "label": "x", "tutorial_id": "ghost.tutorial"},
            {"type": "start_tutorial", "label": "ok", "tutorial_id": "doctor.create"},
            {"type": "show_me", "label": "bad", "target": {"css": "div:nth-child(3)"}, "reveal": []},
            {"type": "show_me", "label": "bad2", "target": {"action": "does.not.exist"}, "reveal": []},
            {"type": "show_me", "label": "good", "target": {"action": "nav.patients"}, "reveal": [{"action": "nav.menu.open"}]},
            {"type": "choose", "label": "c", "intent": "ghost"},
            {"type": "click_save", "label": "evil"},
        ],
    }
    clean = service.validate_response(raw, ctx(), kb)
    assert "<" not in clean["message"] and clean["tutorial_id"] is None
    assert [a["type"] for a in clean["actions"]] == ["start_tutorial", "show_me"]
    assert service.validate_response({"type": "html", "message": "x"}, ctx(), kb)["type"] == "error"


def test_all_response_types_are_in_the_contract():
    assert service.RESPONSE_TYPES == {"explanation", "tutorial_suggestion", "tutorial_started", "clarification", "not_found", "error"}


# -------------------------------------------------------- registry integrity

def test_knowledge_registry_loads_and_every_tutorial_reference_exists():
    kb = kb_mod.load()
    assert {"doctor.create", "specialty.create"} <= set(kb.entries)
    assert all(not e.tutorial or e.tutorial in registry.load_all() for e in kb.entries.values())


def test_every_ui_reference_exists_in_the_ui_sources():
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in [ROOT / "templates/clinics/workspace.html", *(ROOT / "static/clinics").glob("*.js")])
    attr = {"action": "data-finora-action", "section": "data-finora-section", "field": "data-finora-field"}
    missing = [r for r in kb_mod.ui_references() for kind, ident in [next(iter(r.items()))] if f'{attr[kind]}="{ident}"' not in corpus]
    assert not missing, missing


def test_pages_match_the_real_clinic_pages():
    from modules.clinics.routes import PAGE_CONFIG

    assert set(kb_mod.load().pages) <= set(PAGE_CONFIG) | {"dashboard", "activity"}


# ------------------------------------------------------- context + rate limit

def test_route_and_page_are_sanitised():
    assert chat_context.safe_route("/clinics/patients/123?name=Ahmed") == "/clinics/patients/:id"
    assert chat_context.safe_route("https://evil.example/x") is None
    assert chat_context.safe_route(["x"]) is None


def test_sliding_window_limiter():
    now = [0.0]
    limiter = ratelimit.SlidingWindowLimiter(3, 10, clock=lambda: now[0])
    assert [limiter.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry = limiter.check("a")
    assert allowed is False and 1 <= retry <= 11
    assert limiter.check("b")[0] is True  # independent keys
    now[0] = 11
    assert limiter.check("a")[0] is True


# ------------------------------------------------------------------------ API

@pytest.fixture(autouse=True)
def _fresh_limits():
    ratelimit.USER_LIMITER.reset()
    ratelimit.TENANT_LIMITER.reset()
    yield
    ratelimit.USER_LIMITER.reset()
    ratelimit.TENANT_LIMITER.reset()


def ask(client, message="", **extra):
    res = client.post(BASE + "/ask", json={"message": message, **extra})
    return res, (res.get_json() or {}).get("response")


def test_ask_requires_login_and_feature(tutor_app):
    assert tutor_app.test_client().post(BASE + "/ask", json={"message": "x"}).status_code == 401
    res, _ = ask(_user(tutor_app), "شلون أضيف طبيب")
    assert res.status_code == 403 and res.get_json() == {"error": "FEATURE_NOT_ENABLED", "feature": "clinic_ai_tutor"}
    _enable(tutor_app)
    assert ask(_user(tutor_app, slug="clinic-b"), "شلون أضيف طبيب")[0].status_code == 403


def test_ask_api_end_to_end_answers(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    res, r = ask(client, "شلون أضيف طبيب", page="dashboard", route="/clinics/")
    assert res.status_code == 200 and r["type"] == "tutorial_suggestion" and r["tutorial_id"] == "doctor.create"
    assert ask(client, "اريد اسوي تخصص")[1]["tutorial_id"] == "specialty.create"
    assert ask(client, "وين العمليات الجراحية")[1]["type"] == "not_found"
    page = ask(client, "شنو هاي الصفحة", page="staff", route="/clinics/staff")[1]
    assert "أنت حالياً بصفحة الأطباء والموظفون" in page["message"]
    assert ask(client, "أريد أضيف حساب")[1]["type"] == "clarification"
    chosen = client.post(BASE + "/ask", json={"intent": "employee.create"}).get_json()["response"]
    assert chosen["type"] == "tutorial_suggestion" and chosen["tutorial_id"] == "employee.create" and "إضافة موظف" in chosen["message"]


def test_ask_api_validates_input(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    assert client.post(BASE + "/ask", data="not json", content_type="text/plain").status_code == 400
    assert client.post(BASE + "/ask", json={"message": 5}).status_code == 400
    assert client.post(BASE + "/ask", json={"intent": ["x"]}).status_code == 400
    res, r = ask(client, "", page={"evil": 1}, route="javascript:alert(1)")
    assert res.status_code == 200 and r["type"] == "clarification"
    assert len(ask(client, "ا" * 5000)[1]["message"]) <= service.MAX_MESSAGE_CHARS


def test_ask_uses_server_side_progress_not_client_claims(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    spoof = ask(client, "ليش ما يكمل", active={"tutorial_id": "doctor.create", "step_id": "save", "issue": "validation_failed"})[1]
    assert "ماكو درس شغال" in spoof["message"]  # no server-side run -> claims are ignored
    steps = [s["id"] for s in registry.get("doctor.create")["steps"]]
    client.post(BASE + "/tutorials/doctor.create/start")
    client.post(BASE + "/tutorials/doctor.create/progress", json={"event": "step_completed", "step_id": steps[0], "next_step_id": "name"})
    r = ask(client, "شنو اسوي هسه")[1]
    assert "الاسم الكامل" in r["message"] and r["tutorial_id"] == "doctor.create"
    dep = ask(client, "ليش ما يكمل", active={"issue": "dependency_missing"})[1]  # fixture clinic has no specialty
    assert [a["type"] for a in dep["actions"]] == ["resume_dependency"]


def test_ask_respects_user_permissions(tutor_app):
    _enable(tutor_app)
    r = ask(_user(tutor_app, "plain"), "شلون أضيف طبيب")[1]
    assert not any(a["type"] == "start_tutorial" for a in r["actions"])


def test_ask_is_rate_limited_per_user(tutor_app, monkeypatch):
    _enable(tutor_app)
    monkeypatch.setattr(ratelimit, "USER_LIMITER", ratelimit.SlidingWindowLimiter(3, 60))
    client = _user(tutor_app)
    assert [ask(client, "هلا")[0].status_code for _ in range(3)] == [200, 200, 200]
    res, _ = ask(client, "هلا")
    assert res.status_code == 429 and res.get_json()["error"] == "RATE_LIMITED" and int(res.headers["Retry-After"]) >= 1
    assert ask(_user(tutor_app, "plain"), "هلا")[0].status_code == 200  # other users are not affected


def test_ask_survives_provider_failure(tutor_app, monkeypatch):
    _enable(tutor_app)
    from modules.ai_tutor import routes

    monkeypatch.setattr(routes, "get_provider", lambda: FakeProvider(error=ProviderError("down")))
    client = _user(tutor_app)
    assert ask(client, "وين العمليات الجراحية")[1]["type"] == "not_found"
    assert ask(client, "شلون أضيف طبيب")[1]["type"] == "tutorial_suggestion"


def test_knowledge_endpoint_generates_quick_actions_and_honest_progress(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    data = client.get(BASE + "/knowledge").get_json()
    quick = [q["tutorial_id"] for q in data["quick_actions"]]
    assert {"doctor.create", "specialty.create"} <= set(quick) and len(quick) == len(set(quick))
    assert "شلون أضيف طبيب؟" in data["suggested_prompts"] and "شنو هاي الصفحة؟" in data["suggested_prompts"]
    groups = {g["id"]: g for g in data["plan"]["groups"]}
    assert set(groups) <= {"setup", "operations", "collections"}
    states = {i["id"]: i["state"] for g in groups.values() for i in g["items"]}
    assert {"specialty.create", "doctor.create", "patient.create"} <= set(states) and set(states.values()) == {"available"}
    assert all(i["tutorial_id"] == i["id"] for g in groups.values() for i in g["items"])  # only lessons that exist: no "coming later"
    plain = _user(tutor_app, "plain").get(BASE + "/knowledge").get_json()
    assert plain["quick_actions"] == []
    assert client.get(BASE + "/knowledge").status_code == 200
    client.post(BASE + "/tutorials/doctor.create/start")
    _create_doctor(tutor_app)  # a real doctor created after the lesson started
    assert client.post(BASE + "/tutorials/doctor.create/complete").status_code == 200
    after = {i["id"]: i["state"] for g in client.get(BASE + "/knowledge").get_json()["plan"]["groups"] for i in g["items"]}
    assert after["doctor.create"] == "completed" and after["specialty.create"] == "available"


# ------------------------------------------------ Phase 7: the clinic core journey (Iraqi phrasings)

CORE_INTENTS = [
    ("شلون أضيف مريض", "patient.create"), ("اضيف زبون", "patient.create"), ("مريض جديد", "patient.create"), ("تسجيل مريض", "patient.create"),
    ("احجز موعد", "appointment.create"), ("اسوي موعد", "appointment.create"), ("موعد جديد", "appointment.create"), ("أريد أحجز موعد", "appointment.create"),
    ("المريض وصل", "appointment.checkin"), ("اسجل وصول المريض", "appointment.checkin"),
    ("اضيف المريض للانتظار", "queue.add"), ("المريض ينتظر", "queue.add"),
    ("ابدي زيارة", "visit.start"), ("افتح زيارة", "visit.start"), ("المريض دخل", "visit.start"), ("أريد أبدأ زيارة", "visit.start"),
    ("اضيف خدمة", "service.create"), ("خدمة جديدة", "service.create"),
    ("خطة علاج", "treatment_plan.create"), ("اسوي خطة", "treatment_plan.create"), ("خطة للمريض", "treatment_plan.create"), ("شلون أسوي خطة علاج", "treatment_plan.create"),
    ("اسوي فاتورة", "invoice.create"), ("فاتورة جديدة", "invoice.create"),
    ("اضيف موظف", "employee.create"), ("موظف جديد", "employee.create"),
    ("اغير صلاحيات موظف", "permissions.manage"), ("الصلاحيات", "permissions.manage"),
    ("اسوي دوام", "doctor.schedule"), ("جدول دوام الطبيب", "doctor.schedule"),
]


@pytest.mark.parametrize("phrase,expected", CORE_INTENTS)
def test_core_journey_phrasings_reach_their_lesson(phrase, expected):
    resolution = intents.resolve(phrase)
    assert resolution.intent == expected, (phrase, resolution.intent, resolution.candidates[:3])
    assert resolution.confidence >= intents.CONFIDENT


@pytest.mark.parametrize("phrase", ["اضيف", "اضيف شي", "اضيف حساب", "زيارة", "وصل"])
def test_vague_requests_are_never_answered_confidently(phrase):
    """Ambiguity: several lessons start with the same verb: ask which one, never guess."""
    resolution = intents.resolve(phrase)
    assert resolution.confidence < intents.CONFIDENT and (resolution.intent is None or resolution.confidence < intents.CONFIDENT)
    assert len(resolution.candidates) >= 1


def test_every_core_lesson_is_reachable_from_the_chat_registry():
    kb = kb_mod.load()
    lessons = {e.tutorial for e in kb.entries.values() if e.kind == "feature" and e.tutorial}
    assert {"patient.create", "appointment.create", "appointment.checkin", "queue.add", "visit.start", "service.create",
            "treatment_plan.create", "invoice.create", "employee.create", "permissions.manage", "doctor.schedule"} <= lessons
    # a lesson added to the registry with a knowledge entry becomes available to the chat with no chat code change
    assert all(registry.get(t) for t in lessons)


def test_medical_guard_still_refuses_advice_but_not_the_treatment_plan_feature():
    for advice in ("شنو علاج الصداع", "اعطيني دواء للضغط", "شنو جرعة البنادول"):
        assert intents.resolve(advice).intent == intents.META_MEDICAL, advice
    for feature in ("خطة علاج", "اريد خطة علاج للمريض", "شلون اسوي خطة علاج"):
        assert intents.resolve(feature).intent == "treatment_plan.create", feature
