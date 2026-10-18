"""Phase 8B backend tests: payment.record — the real financial behavior, availability, chat and privacy."""
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.ai_tutor import registry
from modules.ai_tutor.models import TrainingActivityLog, UserTrainingProgress
from tests.test_ai_tutor_backend import BASE, _enable, _user, tutor_app  # noqa: F401  (fixtures)
from tests.test_ai_tutor_journey import _patient, _dental_specialty  # noqa: F401


def _invoice(app, total=500_000, paid=0, status=None, patient=None):
    from modules.clinics.models import ClinicInvoice

    tenant = app.config["IDS"]["tenant"]
    patient = patient or _patient(app)
    n = ClinicInvoice.query.count() + 1
    row = ClinicInvoice(tenant_id=tenant, patient_id=patient.id, invoice_number=f"INV-{n}",
                        total=total, paid=paid, balance=total - paid, status=status or ("paid" if paid >= total else "open"))
    db.session.add(row)
    db.session.commit()
    return row


def _pay(app, invoice, amount, method="cash", notes=None, actor_id=None):
    from modules.clinics import service as clinics_service

    return clinics_service.receive_payment(app.config["IDS"]["tenant"], invoice.id,
                                           {"amount": amount, "method": method, "notes": notes}, actor_id)


# ------------------------------------------------------------------- real financial behavior (not the tutor)

def test_1_full_payment(tutor_app):
    inv = _invoice(tutor_app, total=500_000)
    result = _pay(tutor_app, inv, 500_000)
    assert result["paid"] == 500_000 and result["balance"] == 0 and result["status"] == "paid"


def test_2_partial_payment(tutor_app):
    inv = _invoice(tutor_app, total=500_000)
    result = _pay(tutor_app, inv, 200_000)
    assert result["paid"] == 200_000 and result["balance"] == 300_000 and result["status"] == "partial"


def test_3_zero_rejected(tutor_app):
    inv = _invoice(tutor_app, total=500_000)
    with pytest.raises(ValueError, match="غير صالح"):
        _pay(tutor_app, inv, 0)


def test_4_negative_rejected(tutor_app):
    inv = _invoice(tutor_app, total=500_000)
    with pytest.raises(ValueError, match="غير صالح"):
        _pay(tutor_app, inv, -50_000)  # _money() clamps negative to 0, same error as zero


def test_5_overpayment_rejected(tutor_app):
    """Real finding, not a Phase 8B invention: service.py already rejects amount > balance outright."""
    inv = _invoice(tutor_app, total=500_000)
    with pytest.raises(ValueError, match="أكبر من الرصيد"):
        _pay(tutor_app, inv, 500_001)
    inv2 = _invoice(tutor_app, total=500_000, paid=300_000)
    with pytest.raises(ValueError, match="أكبر من الرصيد"):
        _pay(tutor_app, inv2, 200_001)  # balance is 200_000


def test_6_payment_on_already_paid_invoice_rejected(tutor_app):
    inv = _invoice(tutor_app, total=500_000, paid=500_000)
    assert inv.balance == 0
    with pytest.raises(ValueError, match="أكبر من الرصيد"):
        _pay(tutor_app, inv, 1)


def test_7_invalid_invoice_rejected(tutor_app):
    from modules.clinics import service as clinics_service

    with pytest.raises(ValueError, match="غير موجودة"):
        clinics_service.receive_payment(tutor_app.config["IDS"]["tenant"], 999999, {"amount": 1000}, None)


def test_8_cross_tenant_invoice_is_invisible(tutor_app):
    """Tenant isolation: an invoice_id from another tenant simply does not resolve for this tenant_id."""
    from modules.clinics import service as clinics_service

    inv = _invoice(tutor_app, total=100_000)
    other_tenant_id = tutor_app.config["IDS"]["tenant"] + 999
    with pytest.raises(ValueError, match="غير موجودة"):
        clinics_service.receive_payment(other_tenant_id, inv.id, {"amount": 1000}, None)
    # the real tenant can still pay it: proves the failure above was isolation, not a broken invoice
    result = clinics_service.receive_payment(tutor_app.config["IDS"]["tenant"], inv.id, {"amount": 1000}, None)
    assert result["paid"] == 1000


def test_9_duplicate_submission_documented_gap_and_natural_full_payment_protection(tutor_app):
    """Phase 8B finding (docs/ai-tutor/payment-analysis.md §11): row locking is Postgres-only; on the tenant SQLite
    dialect used here, two sequential identical PARTIAL submissions both succeed (documented, not fixed in Phase 8B).
    A duplicate FULL-amount submission is naturally caught because the second call re-reads the now-zero balance.
    """
    from extensions import db as _db

    assert _db.session.get_bind().dialect.name != "postgresql"  # this test's own DB: confirms the gap applies here
    partial_inv = _invoice(tutor_app, total=500_000)
    _pay(tutor_app, partial_inv, 200_000)
    _pay(tutor_app, partial_inv, 200_000)  # a double-click resubmission of the same partial amount: NOT rejected
    assert partial_inv.balance == 100_000  # two payments were recorded; a real idempotency key would have caught this

    full_inv = _invoice(tutor_app, total=500_000)
    _pay(tutor_app, full_inv, 500_000)
    with pytest.raises(ValueError, match="أكبر من الرصيد"):
        _pay(tutor_app, full_inv, 500_000)  # the second identical submission IS rejected: balance is already 0


def test_10_payment_is_never_actor_the_real_employee_is(tutor_app):
    from modules.clinics.models import ClinicPayment

    inv = _invoice(tutor_app, total=10_000)
    actor = tutor_app.config["IDS"]["owner"]
    _pay(tutor_app, inv, 10_000, actor_id=actor)
    row = ClinicPayment.query.filter_by(invoice_id=inv.id).one()
    assert row.created_by == actor  # the AI Tutor is never recorded as the actor of a financial operation


# ---------------------------------------------------------------------------- lesson: availability + dependency

def test_payment_lesson_requires_billing_permission(tutor_app):
    _enable(tutor_app)
    assert _user(tutor_app, "plain").post(f"{BASE}/tutorials/payment.record/start").status_code in (403, 404)


def test_payment_lesson_chains_to_invoice_create_when_nothing_is_payable(tutor_app):
    """No payable invoice anywhere: /start still succeeds (available), the dependency is the client engine's job."""
    _enable(tutor_app)
    client = _user(tutor_app)
    started = client.post(f"{BASE}/tutorials/payment.record/start")
    assert started.status_code == 200
    dep = registry.get("payment.record")["dependencies"][0]
    assert dep["tutorial"] == "invoice.create" and dep["fact"] == {"name": "payable_invoices_count", "op": "gt", "value": 0}


def test_payment_lesson_is_backend_verified_by_a_real_payment(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    inv = _invoice(tutor_app, total=200_000, status="open")
    client.post(f"{BASE}/tutorials/payment.record/start")
    verify = lambda: client.post(f"{BASE}/tutorials/payment.record/verify", json={"validator": "payment.recorded_since_start"}).get_json()["verified"]
    assert verify() is False
    assert client.post(f"{BASE}/tutorials/payment.record/complete").status_code == 422
    _pay(tutor_app, inv, 200_000, actor_id=tutor_app.config["IDS"]["owner"])
    assert verify() is True
    assert client.post(f"{BASE}/tutorials/payment.record/complete").get_json()["progress"]["status"] == "completed"


def test_payable_invoices_count_fact_excludes_void_cancelled_and_zero_balance(tutor_app):
    from modules.ai_tutor.facts import collect_facts

    tenant = tutor_app.config["IDS"]["tenant"]
    assert collect_facts(tenant)["payable_invoices_count"] == 0
    _invoice(tutor_app, total=100_000, paid=100_000)  # fully paid: not payable
    _invoice(tutor_app, total=100_000, status="void")
    assert collect_facts(tenant)["payable_invoices_count"] == 0
    _invoice(tutor_app, total=100_000)
    assert collect_facts(tenant)["payable_invoices_count"] == 1


# -------------------------------------------------------------------------------- chat, availability wording

def test_fully_paid_invoice_context_blocks_the_suggestion_without_hardcoding_in_chat(tutor_app):
    from modules.ai_tutor.chat import context as chat_context
    from modules.ai_tutor.chat.service import answer

    _enable(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    build = lambda invoice: chat_context.build_context(
        tenant_id=tenant, user_id=tutor_app.config["IDS"]["owner"], role="admin", page="billing", route="/clinics/billing",
        client_active=None, invoice_context=invoice, has_permission=lambda _p: True, permission_names=())
    paid = answer("اسجل دفعة", build({"remaining": 0, "status": "paid"}))
    assert paid["type"] == "explanation" and "مسددة بالكامل" in paid["message"]
    assert not any(a["type"] == "start_tutorial" for a in paid["actions"])
    owed = answer("اسجل دفعة", build({"remaining": 50_000, "status": "partial"}))
    assert owed["type"] == "tutorial_suggestion" and owed["tutorial_id"] == "payment.record"
    normal = answer("اسجل دفعة", build(None))  # no invoice open: ordinary suggestion, not blocked
    assert normal["type"] == "tutorial_suggestion"


def test_invoice_context_is_sanitized_and_never_reaches_the_llm_payload():
    from modules.ai_tutor.chat.context import safe_invoice_context
    from modules.ai_tutor.chat.privacy import build_llm_payload

    assert safe_invoice_context({"remaining": 100, "status": "partial", "patient_name": "احمد", "phone": "0770"}) == {
        "remaining": 100, "status": "partial"}
    assert safe_invoice_context({"remaining": -5, "status": "open"}) is None
    assert safe_invoice_context({"remaining": "x"}) is None
    assert safe_invoice_context("not a dict") is None
    assert safe_invoice_context({"remaining": 10, "status": "definitely-not-a-real-status"}) == {"remaining": 10, "status": None}
    ctx = {"page": "billing", "active_tutorial": None, "invoice_context": {"remaining": 0, "status": "paid"}}
    payload = build_llm_payload("اسجل دفعة", ctx)
    assert "invoice_context" not in payload and "invoice" not in payload and set(payload) == {"message", "page", "active_tutorial", "intents"}


@pytest.mark.parametrize("phrase", ["اسجل دفعة", "سجل دفع", "الزبون دفع", "استلمت المبلغ", "دفع الفاتورة"])
def test_payment_record_phrasings(phrase):
    from modules.ai_tutor.chat import intent as intents

    r = intents.resolve(phrase)
    assert r.intent in ("payment.record", None), (phrase, r.intent)
    if r.intent is None:
        assert {"payment.record", "payment.history"} <= {c for c, _ in r.candidates}


@pytest.mark.parametrize("phrase", ["دفعة جزئية", "دفع جزء", "سدد جزء", "دفع نص المبلغ"])
def test_payment_partial_phrasings(phrase):
    from modules.ai_tutor.chat import intent as intents

    assert intents.resolve(phrase).intent == "payment.partial"


@pytest.mark.parametrize("phrase", ["شكد باقي عليه", "شكد المتبقي", "شكد باقي بالفاتورة", "المبلغ الباقي"])
def test_invoice_outstanding_phrasings(phrase):
    from modules.ai_tutor.chat import intent as intents

    assert intents.resolve(phrase).intent == "invoice.outstanding"


@pytest.mark.parametrize("phrase", ["دفعات الفاتورة", "سجل الدفع", "شنو دافع قبل", "عرض الدفعات"])
def test_payment_history_phrasings(phrase):
    from modules.ai_tutor.chat import intent as intents

    r = intents.resolve(phrase)
    assert r.intent in ("payment.history", None)


def test_ambiguous_the_patient_paid_asks_to_choose_record_or_view():
    from modules.ai_tutor.chat import intent as intents

    r = intents.resolve("المريض دفع")
    assert r.intent is None and {"payment.record", "payment.history"} <= {c for c, _ in r.candidates}


@pytest.mark.parametrize("phrase", ["الغاء فاتورة", "عكس دفعة", "حذف دفعة"])
def test_void_reverse_delete_phrasings_are_refused_not_redirected(phrase):
    from modules.ai_tutor.chat import intent as intents
    from modules.ai_tutor.chat.service import NO_REVERSAL_TEXT, answer

    r = intents.resolve(phrase)
    assert r.intent == intents.META_NO_REVERSAL
    reply = answer(phrase, {
        "page": None, "route": None, "user_role": "admin", "permissions": [], "available_tutorials": {"payment.record"},
        "runnable_tutorials": {"payment.record"}, "unavailable_reasons": {}, "invoice_context": None,
        "active_tutorial": None, "issue": None, "facts": {},
    })
    assert reply["type"] == "explanation" and reply["message"] == NO_REVERSAL_TEXT
    assert reply["tutorial_id"] is None and reply["actions"] == []


@pytest.mark.parametrize("phrase", ["اريد ارجع المبلغ", "استرداد", "استرجع المبلغ"])
def test_refund_phrasings_resolve_to_the_real_refund_feature(phrase):
    from modules.ai_tutor.chat import intent as intents

    r = intents.resolve(phrase)
    assert r.intent != intents.META_NO_REVERSAL
    assert r.intent == "refund.record" or "refund.record" in {c for c, _ in r.candidates}


def test_no_tutorial_in_the_registry_targets_void_posting_reverse_or_cancel():
    # "refund" is legitimate for refund.record itself (a real, separate feature); every other lesson must
    # never touch it. Void/posting/reverse/cancel have no real UI or backend workflow and stay forbidden for all.
    always_forbidden = ("void", "posting", "reverse", "cancel")
    for lesson in registry.load_all().values():
        forbidden = always_forbidden if lesson["id"] == "refund.record" else always_forbidden + ("refund",)
        for step in lesson["steps"]:
            for ref in registry.target_refs(step):
                value = next(iter(ref.values()))
                assert not any(word in value for word in forbidden), (lesson["id"], step["id"], value)


# ------------------------------------------------------------------------------------------- privacy

def test_payment_training_logs_never_contain_amounts_or_methods(tutor_app):
    """Realistic client traffic only (the real engine.js never sends free-typed field values as `detail` — it sends
    either a fixed machine code or a "kind:id" target reference, e.g. "field:payment.amount"). A free-text detail
    with spaces (what a buggy caller sending real user input would look like) is dropped, matching Phase 7 policy.
    See docs/ai-tutor/payment-analysis.md §16 for the separate, pre-existing, documented-not-fixed finding that this
    regex does not itself recognize a *bare* digit run (an amount with no separators) as unsafe.
    """
    _enable(tutor_app)
    client = _user(tutor_app)
    inv = _invoice(tutor_app, total=777_000)
    client.post(f"{BASE}/tutorials/payment.record/start")
    for detail in ("field:payment.amount", "دفعت 777000 نقدا", "method=zain amount=200000", "x" * 200):
        client.post(f"{BASE}/tutorials/payment.record/progress", json={"event": "target_missing", "step_id": "amount", "detail": detail})
        client.post(f"{BASE}/tutorials/payment.record/resume")
    _pay(tutor_app, inv, 777_000, actor_id=tutor_app.config["IDS"]["owner"])
    client.post(f"{BASE}/tutorials/payment.record/complete")
    rows = TrainingActivityLog.query.filter_by(tutorial_id="payment.record").all()
    assert len(rows) >= 5
    details = [r.detail for r in rows if r.event == "target_missing"]
    assert details == ["field:payment.amount", None, None, None]
    dump = "|".join(f"{r.event}:{r.step_id}:{r.detail}" for r in rows)
    assert "777000" not in dump and "200000" not in dump and "zain" not in dump


def test_payment_lesson_curriculum_slot_and_contract():
    d = registry.get("payment.record")
    assert d["status"] in ("draft", "verified")
    assert d["curriculum"] == {"group": "collections", "order": 1}
    assert d["availability"] == {"required_features": ["billing"]}
    assert d["requires_permissions"] == ["clinics_billing"]
