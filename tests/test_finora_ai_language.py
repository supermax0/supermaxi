"""Dialect routing regressions: new subjects must override stale identities."""
import json
from datetime import datetime
import pytest
from modules.finora_ai.language import normalize, period_args, selected_candidate
from modules.finora_ai.providers import BuiltinReadOnlyProvider, SYSTEM_PROMPT
from modules.finora_ai.services import TOOLS


def ask(text, context=None, tools=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\nFINORA_CONTEXT=" + json.dumps(context or {}, ensure_ascii=False)}, {"role": "user", "content": text}]
    return BuiltinReadOnlyProvider().chat(messages, tools if tools is not None else [{"name": name} for name in TOOLS])


def test_agent_question_does_not_reuse_previous_order():
    reply = ask("شكد باقي على المندوب", {"active_entity": "order", "order_id": 1716})
    assert not reply.tool_calls and "أي مندوب" in reply.content


def test_unresolved_new_subject_cannot_fall_back_to_old_customer():
    reply = ask("شكد عليه", {"subject": "agent", "order_id": 1716, "customer_id": 1, "awaiting_agent": True})
    assert not reply.tool_calls


@pytest.mark.parametrize("text,tool,args", [
    ("شكد باقي على المندوب وسام", "search_delivery_agents", {"query": "وسام"}),
    ("كشوف المندوب وسام رحيم", "search_delivery_agents", {"query": "وسام رحيم"}),
    ("شكد باقي على الزبون أحمد", "search_customer", {"query": "أحمد", "limit": 10}),
    ("حساب المورد علي", "search_supplier", {"query": "علي", "limit": 10}),
    ("شنو حالة كشف AGT-1-20260916-0011", "get_agent_report", {"report_number": "AGT-1-20260916-0011"}),
    ("كشوف المندوب بانتظار التنفيذ", "get_pending_agent_reports", {}),
    ("تفاصيل طلب ١٧١٦", "get_order", {"invoice_id": 1716}),
])
def test_clean_lookup_and_report_identifiers(text, tool, args):
    reply = ask(text, {"active_entity": "order", "order_id": 99})
    assert len(reply.tool_calls) == 1
    assert (reply.tool_calls[0].name, reply.tool_calls[0].arguments) == (tool, args)


def test_unique_named_agent_balance_chains_to_report_tool():
    messages = [{"role": "system", "content": "FINORA_CONTEXT={}"}, {"role": "user", "content": "شكد باقي على المندوب وسام"},
                {"role": "tool", "content": json.dumps({"success": True, "meta": {"tool": "search_delivery_agents"}, "data": {"items": [{"agent_id": 1, "name": "وسام"}]}})}]
    result = BuiltinReadOnlyProvider().chat(messages, [{"name": name} for name in TOOLS])
    assert result.tool_calls[0].name == "get_delivery_agent_reports"
    assert result.tool_calls[0].arguments == {"agent_id": 1}


def test_multiple_agents_require_explicit_selection():
    result = BuiltinReadOnlyProvider()._present({"success": True, "data": {"items": [{"agent_id": 1, "name": "وسام أ"}, {"agent_id": 2, "name": "وسام ب"}]}})
    assert "حدد المطلوب" in result
    reply = ask("الثاني", {"candidate_type": "agent", "candidates": [{"id": 1, "name": "وسام أ"}, {"id": 2, "name": "وسام ب"}]})
    assert reply.tool_calls[0].arguments == {"agent_id": 2}


def test_missing_tool_is_explained_without_wrong_substitute():
    reply = ask("كشوف المندوب وسام", tools=[{"name": "get_order"}])
    assert not reply.tool_calls and "غير متاحة" in reply.content


def test_financial_pronoun_uses_active_supplier_not_stale_customer():
    reply = ask("شكد عليه", {"active_entity": "supplier", "supplier_id": 8, "customer_id": 1})
    assert reply.tool_calls[0].name == "get_supplier_balance"
    assert reply.tool_calls[0].arguments == {"supplier_id": 8}


@pytest.mark.parametrize("text,start,end", [("مبيعات أمس", "2026-09-16", "2026-09-16"), ("مبيعات هالشهر", "2026-09-01", "2026-09-17"), ("مبيعات الشهر الفات", "2026-08-01", "2026-08-31"), ("مبيعات هالأسبوع", "2026-09-13", "2026-09-17")])
def test_relative_periods_use_baghdad_dates(text, start, end):
    assert period_args(text, datetime(2026, 9, 17)) == {"date_from": start, "date_to": end}


def test_normalization_and_greeting_do_not_invent_business_facts():
    assert normalize("أَحْمَد ١٢٣") == "احمد 123"
    reply = ask("هلا")
    assert not reply.tool_calls and "هلا" in reply.content


def test_empty_agent_reports_are_not_presented_as_zero_balance():
    reply = BuiltinReadOnlyProvider()._present({"success": True, "data": {"reports": []}})
    assert "لا يثبت" in reply and "صفر" in reply


def test_unsupported_period_requests_dates_instead_of_default_today():
    reply = ask("شكد مبيعات قبل شهرين")
    assert not reply.tool_calls and "تاريخ" in reply.content


def test_last_week_and_last_seven_days_are_distinct():
    now = datetime(2026, 9, 17)
    assert period_args("مبيعات الاسبوع الفات", now) == {"date_from": "2026-09-06", "date_to": "2026-09-12"}
    assert period_args("مبيعات اخر 7 ايام", now) == {"date_from": "2026-09-11", "date_to": "2026-09-17"}


def test_normalized_duplicate_names_require_id_or_ordinal_selection():
    candidates = [{"id": 1, "name": "إياد"}, {"id": 2, "name": "اياد"}]
    assert selected_candidate("اياد", candidates) is None
    assert selected_candidate("الثاني", candidates)["id"] == 2
