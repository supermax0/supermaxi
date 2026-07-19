from utils.investment_planner import (
    _fallback_plan,
    _normalize_plan_payload,
    calculate_safe_investment_budget,
    sanitize_plan_numbers,
)


def _snapshot(project_scope="mixed", financial_override=None):
    financial = {
        "total_liquidity": 10_000_000,
        "expenses_period": 1_000_000,
        "cash_outflow": 800_000,
        "supplier_debts": 2_000_000,
        "net_cash_flow": 1_500_000,
        "total_revenue": 8_000_000,
        "net_profit_period": 2_000_000,
        "profit_margin_pct": 18.5,
    }
    if financial_override:
        financial.update(financial_override)
    return {
        "budget": calculate_safe_investment_budget(financial, "balanced"),
        "financial": financial,
        "leaders": {
            "top_products": [{"name": "A Product"}],
            "top_pages": [{"name": "Instagram"}],
        },
        "strategy": {
            "project_scope": project_scope,
            "project_scope_label": {
                "mixed": "محفظة مختلطة",
                "outside": "خارج التخصص بالكامل",
                "adjacent": "قريب من النشاط",
            }.get(project_scope, "محفظة مختلطة"),
            "project_scope_description": "اختبار نطاق المشاريع",
        },
        "period": {"label": "آخر 30 يوم"},
    }


def test_safe_investment_budget_keeps_operating_buffer():
    financial = {
        "total_liquidity": 10_000_000,
        "expenses_period": 1_000_000,
        "cash_outflow": 700_000,
        "supplier_debts": 2_000_000,
        "net_cash_flow": 500_000,
    }

    result = calculate_safe_investment_budget(financial, "balanced")

    assert result["operating_buffer"] == 1_500_000
    assert result["free_cash_after_buffer"] == 8_500_000
    assert result["recommended_budget"] == 4_250_000


def test_negative_cash_flow_halves_budget():
    financial = {
        "total_liquidity": 10_000_000,
        "expenses_period": 1_000_000,
        "cash_outflow": 700_000,
        "supplier_debts": 2_000_000,
        "net_cash_flow": -1,
    }

    result = calculate_safe_investment_budget(financial, "balanced")

    assert result["recommended_budget"] == 2_125_000


def test_fallback_plan_returns_three_complete_proposals():
    plan = _normalize_plan_payload(None, _snapshot())

    assert len(plan["proposals"]) == 3
    assert plan["recommendation"]["selected_index"] == 0
    assert all(item["required_capital"] >= 0 for item in plan["proposals"])
    assert all(item["implementation_plan"] for item in plan["proposals"])
    assert plan["investment_capacity"]["level"]
    assert plan["board_brief"]
    assert plan["funding_policy"]
    assert plan["rejected_options"]
    assert all(item["capacity_fit"] for item in plan["proposals"])
    assert all(item["stop_loss_rules"] for item in plan["proposals"])
    assert any(item["is_outside_specialty"] for item in plan["proposals"])
    assert any(item["risk_level"] in {"منخفض", "Ù…Ù†Ø®ÙØ¶"} for item in plan["proposals"])


def test_outside_scope_returns_external_projects_not_top_product():
    plan = _normalize_plan_payload(None, _snapshot("outside"))

    assert len(plan["proposals"]) == 3
    assert all(item["is_outside_specialty"] for item in plan["proposals"])
    assert all("A Product" not in item["title"] for item in plan["proposals"])
    assert all(item["validation_plan"] for item in plan["proposals"])
    assert all(item["external_partners"] for item in plan["proposals"])


def test_weak_liquidity_keeps_outside_project_small_or_zero():
    snapshot = _snapshot(
        "outside",
        {
            "total_liquidity": 1_000_000,
            "expenses_period": 1_500_000,
            "cash_outflow": 1_500_000,
            "supplier_debts": 1_000_000,
            "net_cash_flow": -100_000,
        },
    )
    plan = _normalize_plan_payload(None, snapshot)
    safe_budget = snapshot["budget"]["recommended_budget"]

    assert safe_budget == 0
    assert all(item["required_capital"] <= safe_budget for item in plan["proposals"])
    assert all(item["validation_plan"] for item in plan["proposals"])


def test_normalizer_caps_ai_capital_to_safe_budget():
    snapshot = _snapshot()
    budget = snapshot["budget"]["recommended_budget"]
    payload = {
        "executive_summary": "AI summary",
        "proposals": [
            {"title": "Too large", "required_capital": budget * 10, "expected_monthly_profit": 100_000},
            {"title": "Valid", "required_capital": 100, "expected_monthly_profit": 10},
            {"title": "Sparse"},
        ],
        "recommendation": {"selected_index": 9, "reason": "Pick it"},
    }

    normalized = _normalize_plan_payload(payload, snapshot)

    assert len(normalized["proposals"]) == 3
    assert normalized["proposals"][0]["required_capital"] == budget
    assert normalized["recommendation"]["selected_index"] == 2


def test_sanitizer_recomputes_unrealistic_profit_and_payback():
    snapshot = _snapshot()
    payload = {
        "proposals": [
            {
                "title": "Old saved plan",
                "required_capital": 50_000_000,
                "expected_monthly_revenue": 10_000_000,
                "expected_monthly_profit": 2_000_000,
                "payback_months": 30,
                "budget_breakdown": [{"label": "Inventory", "amount": 70_000_000}],
            }
        ]
    }

    sanitized, changed = sanitize_plan_numbers(payload, snapshot)
    proposal = sanitized["proposals"][0]

    assert changed is True
    assert proposal["required_capital"] == snapshot["budget"]["recommended_budget"]
    assert proposal["expected_monthly_profit"] <= proposal["number_audit"]["monthly_profit_cap"]
    assert proposal["payback_months"] == round(proposal["required_capital"] / proposal["expected_monthly_profit"], 1)
    assert sum(item["amount"] for item in proposal["budget_breakdown"]) == proposal["required_capital"]
