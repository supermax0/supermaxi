"""Investment proposal generation for Finora financial data."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from copy import deepcopy
from typing import Any

from flask import current_app

from extensions import db
from models.investment_proposal import InvestmentProposal
from utils.financial_report_data import get_financial_report_data


RISK_MULTIPLIERS = {
    "conservative": 0.35,
    "balanced": 0.50,
    "growth": 0.70,
}


def _money(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _clip(text: Any, limit: int = 180) -> str:
    text_value = str(text or "").strip()
    return text_value[:limit]


def _pick_company_settings() -> dict:
    try:
        from models.invoice_settings import InvoiceSettings

        settings = InvoiceSettings.query.first()
        if not settings:
            return {"company_name": "الشركة", "report_logo": None, "report_address": "", "report_phone": ""}

        def pick(*vals):
            for val in vals:
                if val is not None and str(val).strip():
                    return val
            return None

        return {
            "company_name": pick(getattr(settings, "report_company_name", None), settings.company_name) or "الشركة",
            "report_logo": pick(getattr(settings, "report_logo_path", None), settings.logo_path)
            if getattr(settings, "report_show_logo", True)
            else None,
            "report_address": pick(getattr(settings, "report_address", None), settings.company_address) or "",
            "report_phone": pick(getattr(settings, "report_phone", None), settings.company_phone) or "",
            "report_footer": pick(getattr(settings, "report_footer_text", None))
            or "تقرير استثماري تقديري مولد من نظام Finora",
        }
    except Exception:
        return {"company_name": "الشركة", "report_logo": None, "report_address": "", "report_phone": ""}


def calculate_safe_investment_budget(financial: dict, risk_profile: str = "balanced") -> dict:
    """Return a conservative deployable budget based only on existing company figures."""
    liquidity = _money(financial.get("total_liquidity"))
    expenses = _money(financial.get("expenses_period"))
    cash_outflow = _money(financial.get("cash_outflow"))
    supplier_debts = _money(financial.get("supplier_debts"))
    net_cash_flow = _money(financial.get("net_cash_flow"))
    multiplier = RISK_MULTIPLIERS.get((risk_profile or "balanced").strip(), RISK_MULTIPLIERS["balanced"])
    operating_buffer = max(int(expenses * 1.5), int(cash_outflow * 1.5), int(supplier_debts * 0.25), 0)
    free_cash = max(liquidity - operating_buffer, 0)
    budget = int(free_cash * multiplier)
    if net_cash_flow < 0:
        budget = int(budget * 0.5)
    return {
        "risk_profile": risk_profile or "balanced",
        "total_liquidity": liquidity,
        "operating_buffer": operating_buffer,
        "free_cash_after_buffer": free_cash,
        "recommended_budget": max(budget, 0),
        "currency": "د.ع",
    }


def _fmt_money(value: Any) -> str:
    return f"{_money(value):,} د.ع"


PROJECT_SCOPE_OPTIONS = {
    "mixed": {
        "label": "محفظة مختلطة",
        "description": "مشروع قريب من النشاط، مشروع مجاور، ومشروع خارج التخصص كتجربة مرحلية.",
    },
    "outside": {
        "label": "خارج التخصص بالكامل",
        "description": "ثلاث فرص خارج نشاط الشركة الحالي، كلها تبدأ كتجارب صغيرة قابلة للإيقاف.",
    },
    "adjacent": {
        "label": "قريب من النشاط",
        "description": "فرص مجاورة تستفيد من العملاء والموردين وقنوات البيع الحالية.",
    },
}


def _normalize_project_scope(value: Any) -> str:
    value = str(value or "mixed").strip().lower()
    return value if value in PROJECT_SCOPE_OPTIONS else "mixed"


def _investment_capacity_profile(snapshot: dict) -> dict:
    financial = snapshot.get("financial") or {}
    budget = snapshot.get("budget") or {}
    recommended_budget = _money(budget.get("recommended_budget"))
    liquidity = _money(financial.get("total_liquidity"))
    expenses = max(_money(financial.get("expenses_period")), 1)
    cash_outflow = max(_money(financial.get("cash_outflow")), 0)
    supplier_debts = _money(financial.get("supplier_debts"))
    receivables = max(_money(financial.get("accounts_receivable")), _money(financial.get("customer_receivables")))
    inventory = _money(financial.get("inventory_value"))
    net_cash_flow = _money(financial.get("net_cash_flow"))
    monthly_revenue = _monthlyized(financial.get("total_revenue"), snapshot)
    monthly_profit = max(_monthlyized(financial.get("net_profit_period"), snapshot), 0)
    margin = 0.0
    try:
        margin = float(financial.get("profit_margin_pct") or 0)
    except (TypeError, ValueError):
        margin = 0.0
    runway_months = round(liquidity / max(expenses, cash_outflow, 1), 1)

    constraints = []
    strengths = []
    if recommended_budget <= 0:
        constraints.append("لا توجد سيولة آمنة كافية للصرف الاستثماري بعد احتساب الالتزامات والتشغيل.")
    if net_cash_flow < 0:
        constraints.append("التدفق النقدي للفترة سلبي، لذلك أي مشروع يجب أن يبدأ كتجربة صغيرة قابلة للإيقاف.")
    if margin and margin < 6:
        constraints.append("هامش الربح منخفض؛ الأفضل مشاريع ترفع الهامش أو تقلل الكلفة قبل التوسع الكبير.")
    if supplier_debts > liquidity * 0.35:
        constraints.append("ديون الموردين مرتفعة قياساً بالسيولة، ويجب حماية النقد قبل فتح التزامات جديدة.")
    if receivables > max(monthly_revenue * 0.45, 1):
        constraints.append("الذمم عالية قياساً بالمبيعات، والتحصيل يجب أن يكون جزءاً من أي خطة نمو.")
    if runway_months < 2:
        constraints.append("غطاء التشغيل أقل من شهرين، لذلك المخاطرة الاستثمارية يجب أن تكون محدودة.")

    if liquidity > expenses * 3:
        strengths.append("السيولة تغطي التشغيل لفترة مريحة نسبياً.")
    if monthly_revenue > 0:
        strengths.append("توجد مبيعات فعلية يمكن البناء عليها بدل الاعتماد على فرضيات سوقية.")
    if monthly_profit > 0:
        strengths.append("الشركة تحقق ربحاً فعلياً في الفترة المختارة.")
    if inventory > 0:
        strengths.append("يوجد مخزون/أصول تشغيلية يمكن تحسين دورانها ضمن الخطة.")

    if recommended_budget <= 0 or runway_months < 1.5:
        level = "دفاعي"
        posture = "حماية النقد أولاً"
        max_single_project = 0
        allowed_types = ["تحصيل الذمم", "خفض المصاريف", "تصفية المخزون الراكد", "تحسين التسعير"]
    elif recommended_budget < max(monthly_revenue * 0.12, expenses):
        level = "حذر"
        posture = "تجارب صغيرة قبل التوسع"
        max_single_project = int(recommended_budget * 0.55)
        allowed_types = ["دفعة مخزون محدودة", "حملة أداء قصيرة", "تحسين التحصيل", "شراكات بالعمولة"]
    elif recommended_budget < max(monthly_revenue * 0.35, expenses * 3):
        level = "متوازن"
        posture = "توسع مضبوط على مراحل"
        max_single_project = int(recommended_budget * 0.70)
        allowed_types = ["توسيع أفضل المنتجات", "قناة بيع جديدة", "تحسين سلسلة التوريد", "تجهيز فريق صغير"]
    else:
        level = "هجومي محسوب"
        posture = "توسع أكبر مع بوابات رقابة"
        max_single_project = int(recommended_budget * 0.80)
        allowed_types = ["خط إنتاج/قسم جديد", "فرع تجريبي", "منصة تجارة إلكترونية", "شراكات توريد وتسويق"]

    return {
        "level": level,
        "posture": posture,
        "project_scope": _normalize_project_scope((snapshot.get("strategy") or {}).get("project_scope")),
        "project_scope_label": PROJECT_SCOPE_OPTIONS[_normalize_project_scope((snapshot.get("strategy") or {}).get("project_scope"))]["label"],
        "runway_months": runway_months,
        "monthly_revenue_base": monthly_revenue,
        "monthly_profit_base": monthly_profit,
        "safe_budget": recommended_budget,
        "max_single_project_capital": max(max_single_project, 0),
        "reserve_required": _money(budget.get("operating_buffer")),
        "allowed_project_types": allowed_types,
        "strengths": strengths[:6],
        "constraints": constraints[:8],
        "decision_rule": "لا يتم رفع رأس المال إلا بعد تحقق 70% من مؤشرات أول 30 يوم وبقاء التدفق النقدي موجباً.",
    }


def collect_investment_context(
    period_type: str = "last_30_days",
    custom_date_from: str | None = None,
    custom_date_to: str | None = None,
    risk_profile: str = "balanced",
    project_scope: str = "mixed",
) -> dict:
    financial = get_financial_report_data(period_type, custom_date_from, custom_date_to)
    settings = _pick_company_settings()
    budget = calculate_safe_investment_budget(financial, risk_profile)
    project_scope = _normalize_project_scope(project_scope)
    snapshot = {
        "company": settings,
        "period": {
            "type": period_type,
            "label": financial.get("period_label"),
            "date_from": financial.get("date_from").isoformat() if financial.get("date_from") else None,
            "date_to": financial.get("date_to").isoformat() if financial.get("date_to") else None,
        },
        "strategy": {
            "project_scope": project_scope,
            "project_scope_label": PROJECT_SCOPE_OPTIONS[project_scope]["label"],
            "project_scope_description": PROJECT_SCOPE_OPTIONS[project_scope]["description"],
            "risk_gate": "تجربة مرحلية 30/60/90 يوم قبل أي توسع كبير خارج التخصص.",
        },
        "budget": budget,
        "financial": {
            key: financial.get(key)
            for key in (
                "total_revenue",
                "cash_sales",
                "credit_sales",
                "gross_profit",
                "expenses_period",
                "net_profit_period",
                "cash_balance",
                "bank_balance_total",
                "total_liquidity",
                "inventory_value",
                "accounts_receivable",
                "customer_receivables",
                "supplier_debts",
                "shipping_receivables",
                "total_assets",
                "total_liabilities",
                "equity",
                "cash_inflow",
                "cash_outflow",
                "net_cash_flow",
                "gross_margin_pct",
                "profit_margin_pct",
                "expense_to_revenue_pct",
                "liquidity_ratio",
                "growth_revenue_pct",
                "growth_profit_pct",
                "low_stock_count",
                "zero_stock_count",
            )
        },
        "leaders": {
            "top_products": (financial.get("top_products") or [])[:8],
            "top_customers": (financial.get("top_customers") or [])[:8],
            "top_employees": (financial.get("top_employees") or [])[:6],
            "top_pages": (financial.get("top_pages") or [])[:6],
            "top_suppliers": (financial.get("top_suppliers") or [])[:6],
        },
        "chart_series": financial.get("chart_series") or [],
    }
    snapshot["investment_capacity"] = _investment_capacity_profile(snapshot)
    return snapshot


def _json_from_text(text: str) -> dict | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _budget_items(total: int, labels: list[str]) -> list[dict]:
    if total <= 0:
        return [{"label": labels[0], "amount": 0}]
    weights = [0.45, 0.25, 0.18, 0.12]
    items = []
    for index, label in enumerate(labels[:4]):
        amount = int(total * weights[index]) if index < len(weights) - 1 else total - sum(i["amount"] for i in items)
        items.append({"label": label, "amount": max(amount, 0)})
    return items


def _period_days(snapshot: dict) -> int:
    period = snapshot.get("period") or {}
    try:
        start = datetime.strptime(str(period.get("date_from") or ""), "%Y-%m-%d").date()
        end = datetime.strptime(str(period.get("date_to") or ""), "%Y-%m-%d").date()
        return max((end - start).days + 1, 1)
    except Exception:
        return 30


def _monthlyized(value: Any, snapshot: dict) -> int:
    return int(_money(value) * 30 / max(_period_days(snapshot), 1))


def _risk_factor(snapshot: dict, conservative: float, balanced: float, growth: float) -> float:
    risk = ((snapshot.get("budget") or {}).get("risk_profile") or "balanced").strip()
    return {"conservative": conservative, "balanced": balanced, "growth": growth}.get(risk, balanced)


def _projection_limits(snapshot: dict, required_capital: int = 0) -> dict:
    financial = snapshot.get("financial") or {}
    period_revenue = max(
        _money(financial.get("total_revenue")),
        _money(financial.get("cash_sales")) + _money(financial.get("credit_sales")),
        _money(financial.get("cash_inflow")),
    )
    monthly_revenue_base = _monthlyized(period_revenue, snapshot)
    monthly_profit_base = max(_monthlyized(financial.get("net_profit_period"), snapshot), 0)
    margin_values = []
    for key in ("profit_margin_pct", "gross_margin_pct"):
        try:
            value = float(financial.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if 0 < value < 80:
            margin_values.append(value / 100)

    observed_margin = max(margin_values) if margin_values else 0.12
    margin_cap = min(max(observed_margin * 1.35, 0.06), 0.28)
    company_revenue_cap = int(monthly_revenue_base * _risk_factor(snapshot, 0.20, 0.35, 0.50))
    capital_turnover_cap = int(max(required_capital, 0) * _risk_factor(snapshot, 0.18, 0.25, 0.35))
    candidates = [value for value in (company_revenue_cap, capital_turnover_cap) if value > 0]
    monthly_revenue_cap = min(candidates) if candidates else int(max(required_capital, 0) * 0.12)
    if monthly_revenue_base > 0:
        monthly_revenue_cap = max(monthly_revenue_cap, int(monthly_revenue_base * 0.08))
    monthly_revenue_cap = max(monthly_revenue_cap, 0)

    profit_from_revenue = int(monthly_revenue_cap * margin_cap)
    profit_from_company = int(monthly_profit_base * _risk_factor(snapshot, 0.35, 0.55, 0.75))
    profit_candidates = [value for value in (profit_from_revenue, profit_from_company) if value > 0]
    monthly_profit_cap = min(profit_candidates) if profit_candidates else profit_from_revenue

    return {
        "monthly_revenue_base": monthly_revenue_base,
        "monthly_profit_base": monthly_profit_base,
        "monthly_revenue_cap": max(monthly_revenue_cap, 0),
        "monthly_profit_cap": max(monthly_profit_cap, 0),
        "margin_cap_pct": round(margin_cap * 100, 2),
    }


def _payback_months(required_capital: int, monthly_profit: int) -> float | None:
    if required_capital <= 0 or monthly_profit <= 0:
        return None
    return round(required_capital / monthly_profit, 1)


def _scale_budget_breakdown(items: list, total: int) -> list[dict]:
    if not items:
        return _budget_items(total, ["رأس مال تشغيلي", "تسويق", "مخزون", "احتياطي"])
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        clean.append({**item, "amount": max(_money(item.get("amount")), 0)})
    if not clean:
        return _budget_items(total, ["رأس مال تشغيلي", "تسويق", "مخزون", "احتياطي"])
    current_total = sum(row["amount"] for row in clean)
    if total <= 0:
        for row in clean:
            row["amount"] = 0
        return clean
    if current_total <= 0:
        return _budget_items(total, [row.get("label") or f"بند {index + 1}" for index, row in enumerate(clean)])
    running = 0
    for index, row in enumerate(clean):
        if index == len(clean) - 1:
            row["amount"] = max(total - running, 0)
        else:
            row["amount"] = int(total * row["amount"] / current_total)
            running += row["amount"]
    return clean


def _scenario_rows(proposal: dict, limits: dict) -> list[dict]:
    capital = _money(proposal.get("required_capital"))
    revenue = _money(proposal.get("expected_monthly_revenue"))
    profit = _money(proposal.get("expected_monthly_profit"))
    margin = max(float(limits.get("margin_cap_pct") or 0) / 100, 0.01)
    rows = [
        ("محافظ", 0.70, 0.60),
        ("متوقع", 1.00, 1.00),
        ("متفائل", 1.20, 1.25),
    ]
    sanitized = []
    for label, revenue_factor, profit_factor in rows:
        row_revenue = min(int(revenue * revenue_factor), _money(limits.get("monthly_revenue_cap")))
        row_profit_cap = min(int(row_revenue * margin), _money(limits.get("monthly_profit_cap")))
        row_profit = min(int(profit * profit_factor), row_profit_cap)
        sanitized.append({
            "case": label,
            "monthly_revenue": max(row_revenue, 0),
            "monthly_profit": max(row_profit, 0),
            "payback_months": _payback_months(capital, row_profit),
        })
    return sanitized


def _ensure_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _professional_enrichment(payload: dict, snapshot: dict) -> tuple[dict, bool]:
    enriched = payload
    changed = False
    capacity = snapshot.get("investment_capacity") or _investment_capacity_profile(snapshot)
    if enriched.get("investment_capacity") != capacity:
        enriched["investment_capacity"] = capacity
        changed = True

    financial = snapshot.get("financial") or {}
    board_brief = [
        f"قدرة الاستثمار الحالية: {capacity.get('level')} - {capacity.get('posture')}.",
        f"السقف الآمن للاستثمار: {_fmt_money(capacity.get('safe_budget'))}، والحد الأعلى للمشروع الواحد: {_fmt_money(capacity.get('max_single_project_capital'))}.",
        f"غطاء التشغيل التقريبي: {capacity.get('runway_months')} شهر، مع احتياطي مطلوب قدره {_fmt_money(capacity.get('reserve_required'))}.",
        "التوصية تعتمد على تجارب قابلة للقياس ثم رفع تدريجي للميزانية عند تحقق مؤشرات الأداء.",
    ]
    if not _ensure_list(enriched.get("board_brief")):
        enriched["board_brief"] = board_brief
        changed = True

    funding_policy = [
        "لا يتم صرف كامل رأس المال دفعة واحدة؛ يقسم الصرف إلى مراحل 30/60/90 يوم.",
        "يبقى احتياطي التشغيل خارج المشروع ولا يدخل ضمن ميزانية التجربة.",
        "أي زيادة رأس مال تحتاج تحقق مؤشرات المبيعات والربح والتدفق النقدي معاً.",
        "إذا انخفض التدفق النقدي أو زادت الذمم بشكل واضح يتم تجميد التوسع فوراً.",
    ]
    if not _ensure_list(enriched.get("funding_policy")):
        enriched["funding_policy"] = funding_policy
        changed = True

    rejected_options = [
        {
            "title": "توسع كبير دفعة واحدة",
            "reason": "يرفع الالتزامات قبل إثبات الطلب الفعلي وقد يضغط السيولة.",
        },
        {
            "title": "خروج من التخصص بدون تجربة",
            "reason": "الخروج من النشاط مقبول فقط إذا بدأ بمرحلة تحقق صغيرة ومصادر وشركاء وبوابات قرار واضحة.",
        },
        {
            "title": "تمويل مخزون بطيء الدوران",
            "reason": "يحبس النقد ويضعف قدرة الشركة على الشراء السريع للمنتجات الرابحة.",
        },
    ]
    if not _ensure_list(enriched.get("rejected_options")):
        enriched["rejected_options"] = rejected_options
        changed = True

    governance = [
        "مراجعة أسبوعية للمبيعات والربح والذمم والمخزون المرتبط بالمشروع.",
        "اعتماد مشتريات المشروع من الإدارة المالية قبل الصرف.",
        "فصل نتائج المشروع عن المبيعات العامة برمز/تصنيف واضح داخل النظام.",
        "تقرير قرار بعد 30 يوم: استمرار، تخفيض، إيقاف، أو رفع تدريجي.",
    ]
    if not _ensure_list(enriched.get("governance")):
        enriched["governance"] = governance
        changed = True

    proposals = enriched.get("proposals") if isinstance(enriched.get("proposals"), list) else []
    for item in proposals:
        if not isinstance(item, dict):
            continue
        if "is_outside_specialty" not in item:
            item["is_outside_specialty"] = False
            changed = True
        capital = _money(item.get("required_capital"))
        profit = _money(item.get("expected_monthly_profit"))
        revenue = _money(item.get("expected_monthly_revenue"))
        max_single = _money(capacity.get("max_single_project_capital"))
        if capital <= max_single or max_single <= 0:
            capacity_fit = "مناسب ضمن سقف المشروع الواحد"
        else:
            capacity_fit = "يحتاج تقليل نطاق أو تقسيم على مراحل قبل الاعتماد"
        defaults = {
            "capacity_fit": capacity_fit,
            "outside_specialty_reason": item.get("outside_specialty_reason") or (
                "هذا المشروع خارج أو مجاور للتخصص، لذلك يعتمد على اختبار سوق صغير قبل أي توسع دائم."
                if item.get("is_outside_specialty")
                else "المشروع قريب من نشاط الشركة ويستفيد من قدراتها الحالية."
            ),
            "roi_logic": [
                f"الإيراد الشهري المتوقع لا يتجاوز سقفاً مرتبطاً بمبيعات الفترة: {_fmt_money(revenue)}.",
                f"الربح الشهري المتوقع مبني على هامش محافظ وليس على رأس المال فقط: {_fmt_money(profit)}.",
                f"الاسترداد يحسب من رأس المال الفعلي مقسوماً على الربح الشهري المتوقع: {item.get('payback_months') or 'غير متاح'} شهر.",
            ],
            "funding_plan": [
                "المرحلة الأولى: صرف محدود لإثبات الطلب وتثبيت المورد/القناة.",
                "المرحلة الثانية: زيادة الصرف فقط إذا تحققت مؤشرات 30 يوم.",
                "المرحلة الثالثة: تثبيت التشغيل أو إيقاف المشروع حسب الربح والتدفق النقدي.",
            ],
            "procurement_plan": [
                "شراء دفعات صغيرة قابلة للدوران بدل طلبية كبيرة واحدة.",
                "تفضيل المورد الذي يقبل تبديل/إرجاع أو دفعات قصيرة الأجل.",
                "تحديد حد إعادة طلب لكل صنف حسب سرعة البيع الفعلية.",
            ],
            "sales_channels": [
                "قناة البيع الحالية الأعلى أداءً من بيانات النظام.",
                "عروض حزم للمنتجات ذات الهامش الأفضل.",
                "متابعة العملاء السابقين قبل صرف حملات اكتساب عالية الكلفة.",
            ],
            "control_points": [
                "مبيعات أسبوعية",
                "هامش ربح فعلي",
                "دوران مخزون",
                "تكلفة اكتساب الطلب",
                "أثر المشروع على التدفق النقدي",
            ],
            "stop_loss_rules": [
                "إيقاف شراء دفعات جديدة إذا لم يتحقق 50% من هدف المبيعات بعد 21 يوم.",
                "خفض الميزانية إذا نزل الهامش الفعلي عن الحد المتوقع لدورتين متتاليتين.",
                "إيقاف المشروع إذا سبب ضغطاً على السيولة أو زاد الذمم دون تحصيل.",
            ],
            "approval_requirements": [
                "موافقة الإدارة على رأس المال والمرحلة الأولى.",
                "موافقة المالية على الموردين وشروط الدفع.",
                "تقرير أداء مختصر قبل أي زيادة رأس مال.",
            ],
            "capability_gap": [
                "توثيق المعرفة التشغيلية المطلوبة قبل الصرف.",
                "تحديد شريك أو موظف مسؤول عن المجال الجديد.",
                "فصل نتائج التجربة محاسبياً عن النشاط الأساسي.",
            ],
            "validation_plan": [
                "اختبار طلب مسبق أو عينة عملاء قبل الشراء.",
                "قياس الهامش والتدفق النقدي أسبوعياً.",
                "إيقاف التجربة إذا لم تظهر مؤشرات طلب واضحة خلال 30 يوم.",
            ],
            "external_partners": [
                {"name": "شريك تشغيل متخصص", "type": "خبرة", "relationship": "تجربة محدودة", "reason": "تقليل مخاطر التعلم"},
                {"name": "مصدر/مورد خارجي", "type": "توريد", "relationship": "دفعات صغيرة", "reason": "تجنب التزام كبير قبل إثبات الطلب"},
            ],
        }
        for key, value in defaults.items():
            if key in ("capacity_fit", "outside_specialty_reason"):
                if not item.get(key):
                    item[key] = value
                    changed = True
            elif not _ensure_list(item.get(key)):
                item[key] = value
                changed = True
        if _money(item.get("learning_cost")) <= 0:
            item["learning_cost"] = int(capital * 0.08) if item.get("is_outside_specialty") else 0
            changed = True

    if not isinstance(enriched.get("strategy"), dict):
        enriched["strategy"] = snapshot.get("strategy") or {"project_scope": "mixed", "project_scope_label": "محفظة مختلطة"}
        changed = True
    enriched["executive_summary"] = enriched.get("executive_summary") or (
        f"توصي الخطة بمحفظة مشاريع ضمن قدرة مالية {capacity.get('level')}، مع صرف مرحلي ورقابة أسبوعية "
        "حتى يبقى التوسع مرتبطاً بالسيولة والمبيعات الفعلية وليس بتوقعات مفتوحة."
    )
    return enriched, changed


def sanitize_plan_numbers(payload: dict, snapshot: dict) -> tuple[dict, bool]:
    """Force all projections to stay tied to the company's real period figures."""
    sanitized = deepcopy(payload or {})
    budget = _money((snapshot.get("budget") or {}).get("recommended_budget"))
    proposals = sanitized.get("proposals") if isinstance(sanitized.get("proposals"), list) else []
    changed = False
    corrections = []

    for index, item in enumerate(proposals):
        if not isinstance(item, dict):
            continue
        original = {
            "required_capital": _money(item.get("required_capital")),
            "expected_monthly_revenue": _money(item.get("expected_monthly_revenue")),
            "expected_monthly_profit": _money(item.get("expected_monthly_profit")),
            "payback_months": item.get("payback_months"),
        }
        original_breakdown = deepcopy(item.get("budget_breakdown") or [])
        original_scenarios = deepcopy(item.get("financial_scenarios") or [])
        capital = max(original["required_capital"], 0)
        if budget and capital > budget:
            capital = budget
        limits = _projection_limits(snapshot, capital)
        revenue_cap = _money(limits.get("monthly_revenue_cap"))
        profit_cap = _money(limits.get("monthly_profit_cap"))

        revenue = original["expected_monthly_revenue"]
        if revenue <= 0:
            revenue = int(revenue_cap * 0.75)
        revenue = min(max(revenue, 0), revenue_cap)

        margin_cap = max(float(limits.get("margin_cap_pct") or 0) / 100, 0.01)
        profit = original["expected_monthly_profit"]
        if profit <= 0:
            profit = int(revenue * margin_cap * 0.75)
        profit = min(max(profit, 0), profit_cap, int(revenue * margin_cap))
        payback = _payback_months(capital, profit)

        item["required_capital"] = capital
        item["expected_monthly_revenue"] = revenue
        item["expected_monthly_profit"] = profit
        item["payback_months"] = payback
        item["budget_breakdown"] = _scale_budget_breakdown(item.get("budget_breakdown") or [], capital)
        item["financial_scenarios"] = _scenario_rows(item, limits)
        item["number_audit"] = {
            "monthly_revenue_cap": revenue_cap,
            "monthly_profit_cap": profit_cap,
            "margin_cap_pct": limits.get("margin_cap_pct"),
            "basis": "تم ربط التوقعات بمبيعات وربح الفترة وسقف الاستثمار الآمن.",
        }

        new_values = {
            "required_capital": capital,
            "expected_monthly_revenue": revenue,
            "expected_monthly_profit": profit,
            "payback_months": payback,
        }
        if (
            new_values != original
            or item.get("budget_breakdown") != original_breakdown
            or item.get("financial_scenarios") != original_scenarios
        ):
            changed = True
            corrections.append({"proposal_index": index, "before": original, "after": new_values})

    sanitized["number_audit"] = {
        "corrected": changed,
        "corrections_count": len(corrections),
        "corrections": corrections[:6],
        "note": "الأرقام تقديرية وتمت مراجعتها آلياً حتى لا تتجاوز قدرة الشركة الحالية أو هامش الربح المنطقي.",
    }
    sanitized, enrichment_changed = _professional_enrichment(sanitized, snapshot)
    changed = changed or enrichment_changed
    sanitized["number_audit"]["corrected"] = changed
    return sanitized, changed


def validate_saved_proposal_numbers(proposal: InvestmentProposal) -> bool:
    payload = proposal.get_payload()
    snapshot = proposal.get_financial_snapshot()
    sanitized, changed = sanitize_plan_numbers(payload, snapshot)
    if changed:
        proposal.set_payload(sanitized)
        proposal.set_sources(sanitized.get("sources") or [])
        proposal.summary = sanitized.get("executive_summary") or proposal.summary
        if proposal.status == "generated":
            proposal.status = "generated_corrected"
    return changed


def _outside_project_overlay(kind: str, capital: int, top_page: str) -> dict:
    common = {
        "is_outside_specialty": True,
        "outside_specialty_reason": "المشروع خارج النشاط الحالي لكنه يبدأ كتجربة محدودة تستفيد من السيولة وقنوات البيع والعلاقات الموجودة بدون التزام كبير.",
        "capability_gap": [
            "تحتاج الشركة معرفة تشغيلية جديدة قبل التوسع.",
            "يجب اختبار الطلب الحقيقي بعينة صغيرة قبل الصرف الكبير.",
            "تحتاج عقود شراكة أو موردين متخصصين لتقليل منحنى التعلم.",
        ],
        "validation_plan": [
            "الأسبوع 1: جمع عروض أسعار ومقابلة 3 شركاء محتملين.",
            "الأسبوع 2: اختبار 10 إلى 20 طلباً أو عميلاً محتملاً فقط.",
            "الأسبوع 3: قياس تكلفة الحصول على الطلب والهامش الفعلي.",
            "نهاية 30 يوم: قرار استمرار أو إيقاف قبل أي زيادة رأس مال.",
        ],
        "learning_cost": int(capital * 0.12),
        "external_partners": [
            {"name": "مورد/مشغل متخصص", "type": "شريك خبرة", "relationship": "تجربة محدودة", "reason": "تقليل مخاطرة الدخول في مجال جديد"},
            {"name": "مسوق أداء محلي", "type": "تسويق", "relationship": "أجر مقابل نتيجة", "reason": "اختبار الطلب قبل التوسع"},
        ],
        "stop_loss_rules": [
            "إيقاف التجربة إذا لم تظهر طلبات فعلية خلال 21 يوم.",
            "عدم زيادة رأس المال إذا لم يثبت هامش ربح موجب في أول دورة.",
            "إيقاف المشروع إذا احتاج التزاماً ثابتاً أكبر من الميزانية المرحلية.",
        ],
    }
    templates = {
        "service": {
            "title": "خدمة تركيب وصيانة منزلية كتجربة خارج النشاط",
            "category": "خدمة خارج التخصص",
            "fit_score": 74,
            "risk_level": "متوسط",
            "summary": "تجربة خدمة تركيب وصيانة مدفوعة لعملاء السوق المحلي، تبدأ بدون مخزون كبير وتعتمد على شريك فني أو فريق صغير عند الطلب. الفكرة خارج نشاط البيع المباشر لكنها تستفيد من قاعدة العملاء والقنوات الحالية، وتسمح بقياس الطلب بسرعة قبل بناء قسم دائم أو توظيف ثابت.",
            "why_now": f"وجود قناة بيع نشطة مثل {top_page} يسمح باختبار الخدمة بإعلانات صغيرة واستبيانات وطلبات مسبقة، مع إبقاء الصرف محدوداً حتى تثبت الحاجة الفعلية.",
            "budget_breakdown": _budget_items(capital, ["تجربة خدمة", "تسويق واختبار طلب", "أدوات بسيطة", "احتياطي"]),
            "staffing": [{"role": "منسق خدمة", "count": 1, "monthly_cost": 0, "responsibility": "تنسيق الطلبات والشركاء وقياس الربحية"}],
            "partners": [{"name": "فنيون مستقلون/ورشة محلية", "type": "تشغيل", "relationship": "بالطلب", "reason": "تقديم الخدمة بدون توظيف دائم بالبداية"}],
            "marketing_plan": [f"اختبار طلب عبر {top_page}", "نموذج طلب خدمة مسبق", "عرض أولي لعملاء سابقين", "حملات صغيرة حسب المنطقة"],
            "kpis": ["طلبات خدمة فعلية", "هامش الخدمة", "وقت التنفيذ", "رضا العملاء", "تكلفة الطلب"],
        },
        "b2b": {
            "title": "قناة توريد B2B للشركات الصغيرة خارج البيع الفردي",
            "category": "قناة تجارية جديدة",
            "fit_score": 78,
            "risk_level": "متوسط",
            "summary": "اختبار قناة توريد للشركات الصغيرة والمكاتب والمتاجر، بحيث تعمل الشركة كمنسق توريد وطلبات مجمعة بدل الاعتماد على البيع الفردي فقط. المشروع مجاور لكنه يفتح شريحة مختلفة، ويبدأ بعروض أسعار وطلبات مسبقة قبل شراء أي كميات كبيرة.",
            "why_now": "الانتقال من طلبات فردية إلى طلبات B2B قد يرفع قيمة الفاتورة الواحدة، لكن يجب اختباره بعقود وطلبات مسبقة حتى لا يتحول إلى ذمم أو مخزون بطيء.",
            "budget_breakdown": _budget_items(capital, ["عروض وتجهيز", "دفعة توريد صغيرة", "متابعة مبيعات", "احتياطي"]),
            "staffing": [{"role": "مسؤول مبيعات شركات", "count": 1, "monthly_cost": 0, "responsibility": "بناء قائمة عملاء B2B ومتابعة العروض"}],
            "partners": [{"name": "موردون يقبلون طلبات مجمعة", "type": "توريد", "relationship": "طلب مسبق", "reason": "تقليل مخاطر المخزون"}],
            "marketing_plan": ["قائمة 50 عميل شركة", "عروض أسعار مسبقة", "زيارات واتساب/هاتف", "قياس معدل تحويل العروض"],
            "kpis": ["عدد عروض الأسعار", "نسبة التحويل", "قيمة الطلب", "أيام التحصيل", "هامش الصفقة"],
        },
        "rental": {
            "title": "تأجير معدات أو أصول خفيفة حسب الطلب",
            "category": "دخل خدمي خارج التخصص",
            "fit_score": 70,
            "risk_level": "عالٍ",
            "summary": "تجربة تأجير أصول خفيفة أو معدات تشغيلية مطلوبة محلياً بدل بيع منتجات فقط. المشروع خارج التخصص ويحتاج تحقق سوقي واضح، لذلك يبدأ بحجز مسبق أو شراكة مع مالكي معدات قبل شراء أصل جديد باسم الشركة.",
            "why_now": "هذا المجال قد يخلق دخلاً متكرراً، لكنه يحمل مخاطر صيانة وتلف وضعف الطلب، لذلك لا يعتمد إلا كتجربة حجوزات وشراكات قبل تملك الأصول.",
            "budget_breakdown": _budget_items(capital, ["حجوزات وتجربة", "تأمين/صيانة", "تسويق محلي", "احتياطي"]),
            "staffing": [{"role": "منسق حجوزات", "count": 1, "monthly_cost": 0, "responsibility": "إدارة الحجوزات والضمانات والتحصيل"}],
            "partners": [{"name": "مالكو معدات/أصول محلية", "type": "تأجير", "relationship": "مشاركة عائد", "reason": "اختبار السوق بدون شراء أصل كامل"}],
            "marketing_plan": ["إعلانات منطقة محدودة", "نموذج حجز مسبق", "ضمانات دفع", "اختبار 15 حجزاً قبل الشراء"],
            "kpis": ["عدد الحجوزات", "نسبة الإشغال", "تكلفة الصيانة", "صافي العائد", "نسبة التلف/الإلغاء"],
        },
        "adjacent": {
            "title": "خدمة تجهيز واشتراكات للعملاء الحاليين",
            "category": "مشروع مجاور",
            "fit_score": 84,
            "risk_level": "منخفض",
            "summary": "مشروع قريب من النشاط لكنه لا يعتمد فقط على بيع منتج واحد؛ يقدم تجهيزات أو باقات أو اشتراكات دورية لعملاء الشركة الحاليين. هذا يسمح بزيادة قيمة العميل والاستفادة من الثقة والقنوات الموجودة مع مخاطرة أقل من دخول مجال بعيد بالكامل.",
            "why_now": "وجود عملاء وقنوات بيع حالية يجعل اختبار الباقات أسهل، ويمكن قياس الطلب بعروض مسبقة قبل الالتزام بمخزون أو فريق كبير.",
            "budget_breakdown": _budget_items(capital, ["تجهيز باقات", "اختبار عروض", "تغليف وخدمة", "احتياطي"]),
            "staffing": [{"role": "مسؤول باقات", "count": 1, "monthly_cost": 0, "responsibility": "تصميم العروض ومتابعة الطلبات المتكررة"}],
            "partners": [{"name": "موردون حاليون وشركاء خدمة", "type": "تشغيل", "relationship": "توريد مرن", "reason": "استغلال العلاقات القائمة"}],
            "marketing_plan": ["عرض لعملاء سابقين", "باقات شهرية", "اختبار سعرين", "متابعة إعادة الشراء"],
            "kpis": ["معدل إعادة الشراء", "متوسط قيمة الطلب", "هامش الباقة", "عدد الاشتراكات", "نسبة الإلغاء"],
            "is_outside_specialty": False,
            "outside_specialty_reason": "مشروع مجاور للنشاط وليس خروجاً كاملاً؛ يستفيد من العملاء والعلاقات الحالية.",
        },
    }
    data = {**common, **templates[kind]}
    data["required_capital"] = max(capital, 0)
    data["expected_monthly_revenue"] = int(capital * 0.28)
    data["expected_monthly_profit"] = int(capital * 0.06)
    data["payback_months"] = _payback_months(data["required_capital"], data["expected_monthly_profit"])
    data["market_research"] = [
        "الطلب غير مثبت داخل بيانات الشركة، لذلك يبدأ المشروع باستبيان وطلبات مسبقة.",
        "يجب مقارنة السعر المحلي مع 3 منافسين أو بدائل قبل الصرف.",
        "الروابط والبحث الخارجي تستخدم للتحقق ولا تعتبر ضماناً للمبيعات.",
    ]
    data["requirements"] = ["شريك خبرة", "نموذج طلب مسبق", "سقف صرف واضح", "تقرير قرار بعد 30 يوم"]
    data["operating_model"] = ["تجربة صغيرة", "بيع/حجز مسبق", "قياس أسبوعي", "توسع فقط بعد تحقق الطلب"]
    data["decision_gates"] = ["بعد 14 يوم: قياس الاهتمام", "بعد 30 يوم: قرار استمرار", "بعد 60 يوم: رفع محدود فقط عند تحقق الربح"]
    data["implementation_plan"] = [
        {"phase": "30 يوم", "days": 30, "actions": ["بحث سوق سريع", "اختيار شريك", "اختبار طلبات مسبقة", "قياس الهامش", "قرار استمرار"]},
        {"phase": "60 يوم", "days": 60, "actions": ["تشغيل محدود", "تثبيت السعر", "تحسين التحصيل", "خفض الكلفة", "إيقاف غير المجدي"]},
        {"phase": "90 يوم", "days": 90, "actions": ["توسيع مشروط", "توثيق التشغيل", "مراجعة المخاطر", "قرار فريق دائم", "تقرير نهائي"]},
    ]
    data["risks"] = ["ضعف الطلب بسبب الخروج من التخصص", "ارتفاع كلفة التعلم", "الاعتماد على شريك خارجي", "تأخر التحصيل"]
    data["assumptions"] = ["المشروع تجربة لا توسع دائم", "الأرقام لا تعتمد على تاريخ مبيعات سابق لهذا المجال", "لا زيادة رأس مال قبل تحقق بوابات القرار"]
    data["sources"] = []
    return data


def _apply_project_scope(proposals: list[dict], snapshot: dict, top_page: str) -> list[dict]:
    scope = _normalize_project_scope(((snapshot.get("strategy") or {}).get("project_scope")))
    budget = _money((snapshot.get("budget") or {}).get("recommended_budget"))
    capacity = snapshot.get("investment_capacity") or {}
    max_single = _money(capacity.get("max_single_project_capital")) or int(budget * 0.55)
    def capital(ratio: float) -> int:
        return max(min(int(budget * ratio), max_single), 0)

    if scope == "outside":
        return [
            _outside_project_overlay("service", capital(0.45), top_page),
            _outside_project_overlay("b2b", capital(0.50), top_page),
            _outside_project_overlay("rental", capital(0.35), top_page),
        ]
    if scope == "adjacent":
        adjusted = list(proposals)
        adjusted[1] = _outside_project_overlay("adjacent", capital(0.45), top_page)
        adjusted[2] = _outside_project_overlay("b2b", capital(0.50), top_page)
        adjusted[2]["is_outside_specialty"] = False
        adjusted[2]["outside_specialty_reason"] = "مشروع مجاور يفتح شريحة عملاء جديدة لكنه يبقى قريباً من قدرات التوريد والبيع الحالية."
        return adjusted

    adjusted = list(proposals)
    adjusted[1] = _outside_project_overlay("adjacent", capital(0.45), top_page)
    adjusted[2] = _outside_project_overlay("service", capital(0.40), top_page)
    return adjusted


def _fallback_plan(snapshot: dict, objective: str = "growth") -> dict:
    budget = _money((snapshot.get("budget") or {}).get("recommended_budget"))
    financial = snapshot.get("financial") or {}
    leaders = snapshot.get("leaders") or {}
    top_product = ((leaders.get("top_products") or [{}])[0] or {}).get("name") or "المنتجات الأعلى مبيعاً"
    top_page = ((leaders.get("top_pages") or [{}])[0] or {}).get("name") or "أفضل قناة بيع"
    margin = financial.get("profit_margin_pct")
    net_profit = _money(financial.get("net_profit_period"))
    monthly_profit_base = max(int(budget * 0.12), int(max(net_profit, 0) * 0.18), 0)

    proposals = [
        {
            "title": f"توسيع مبيعات {top_product}",
            "category": "توسع تجاري",
            "fit_score": 88,
            "risk_level": "متوسط",
            "required_capital": budget,
            "expected_monthly_revenue": int(budget * 0.75),
            "expected_monthly_profit": monthly_profit_base,
            "payback_months": round(budget / monthly_profit_base, 1) if monthly_profit_base else None,
            "summary": "استثمار مركز في المنتجات المثبتة بالمبيعات الحالية بدل الدخول في مجال غير معروف.",
            "why_now": f"هامش الربح الحالي {margin if margin is not None else 'غير محدد'}% مع وجود بيانات مبيعات فعلية.",
            "market_research": [
                "الطلب مثبت داخلياً من مبيعات الفترة، لذلك يبدأ المشروع من أصناف رابحة لا من تخمين سوقي.",
                "الأولوية للمنتجات ذات الربح والدوران العالي، مع استبعاد الأصناف الراكدة أو كثيرة الراجع.",
                "الاختبار العملي يكون بدفعة مخزون محدودة تقاس أسبوعياً قبل رفع رأس المال.",
            ],
            "financial_scenarios": [
                {"case": "محافظ", "monthly_revenue": int(budget * 0.52), "monthly_profit": int(monthly_profit_base * 0.65), "payback_months": round(budget / max(int(monthly_profit_base * 0.65), 1), 1) if budget else None},
                {"case": "متوقع", "monthly_revenue": int(budget * 0.75), "monthly_profit": monthly_profit_base, "payback_months": round(budget / monthly_profit_base, 1) if monthly_profit_base else None},
                {"case": "متفائل", "monthly_revenue": int(budget * 0.95), "monthly_profit": int(monthly_profit_base * 1.35), "payback_months": round(budget / max(int(monthly_profit_base * 1.35), 1), 1) if budget else None},
            ],
            "requirements": ["قائمة SKU رابحة من النظام", "مورد قادر على تسليم سريع", "سقف شراء لا يتجاوز الميزانية", "تتبع يومي للمبيعات والراجع"],
            "operating_model": ["شراء دفعات صغيرة متكررة", "تحديث سعر البيع حسب الهامش", "حملات أداء مرتبطة بكل SKU", "إيقاف المنتج إذا لم يحقق دوراناً خلال 21 يوم"],
            "decision_gates": ["بعد 14 يوم: استمرار فقط للأصناف الأسرع دوراناً", "بعد 30 يوم: مقارنة الربح الفعلي بالمتوقع", "بعد 60 يوم: زيادة رأس المال فقط إذا بقي الهامش موجباً"],
            "budget_breakdown": _budget_items(budget, ["شراء مخزون", "تسويق", "تغليف وتجهيز", "احتياطي تشغيل"]),
            "staffing": [
                {"role": "مسؤول مشتريات", "count": 1, "monthly_cost": 0, "responsibility": "تأمين المخزون والتفاوض مع الموردين"},
                {"role": "مسوق أداء", "count": 1, "monthly_cost": 0, "responsibility": "إدارة الحملات وتحسين تكلفة الطلب"},
            ],
            "partners": [{"name": "أفضل الموردين الحاليين", "type": "مورد", "relationship": "تفاوض دفع/خصم", "reason": "تقليل المخاطرة عبر علاقات موجودة"}],
            "implementation_plan": [
                {"phase": "30 يوم", "days": 30, "actions": ["تحديد SKU الرابحة", "شراء دفعة صغيرة", "قياس سرعة البيع"]},
                {"phase": "60 يوم", "days": 60, "actions": ["زيادة الحملات الناجحة", "تحسين أسعار الشراء"]},
                {"phase": "90 يوم", "days": 90, "actions": ["توسيع المخزون", "تثبيت الموردين الأفضل"]},
            ],
            "marketing_plan": [f"حملة على {top_page}", "إعادة استهداف العملاء السابقين", "عروض حزم للمنتجات الأعلى دوراناً"],
            "kpis": ["هامش الربح", "دوران المخزون", "تكلفة الطلب", "نسبة الراجع"],
            "risks": ["تكدس مخزون إذا انخفض الطلب", "ارتفاع تكلفة الإعلان"],
            "assumptions": ["الأرقام تقديرية مبنية على بيانات الفترة المختارة", "لا يتم تنفيذ أي حركة مالية تلقائياً"],
            "sources": [],
        },
        {
            "title": "تحسين التحصيل والذمم لتمويل النمو",
            "category": "رأس مال عامل",
            "fit_score": 82,
            "risk_level": "منخفض",
            "required_capital": int(budget * 0.35),
            "expected_monthly_revenue": int(budget * 0.35),
            "expected_monthly_profit": int(monthly_profit_base * 0.55),
            "payback_months": 4,
            "summary": "تقوية النقدية عبر تحصيل الذمم وتقليل البيع غير المسدد ثم تدوير المال في المنتجات الرابحة.",
            "why_now": "الذمم والسيولة تظهران مباشرة ضمن التقرير المالي الحالي.",
            "market_research": [
                "هذا المقترح لا يعتمد على سوق خارجي بل على تحسين دورة النقد داخل الشركة.",
                "كل دين يتم تحصيله يقلل الحاجة لتمويل خارجي ويزيد القدرة على الشراء النقدي بخصومات.",
                "يناسب الشركات التي عندها مبيعات جيدة لكن النقدية لا تتحرك بنفس السرعة.",
            ],
            "financial_scenarios": [
                {"case": "محافظ", "monthly_revenue": int(budget * 0.18), "monthly_profit": int(monthly_profit_base * 0.30), "payback_months": 6},
                {"case": "متوقع", "monthly_revenue": int(budget * 0.35), "monthly_profit": int(monthly_profit_base * 0.55), "payback_months": 4},
                {"case": "متفائل", "monthly_revenue": int(budget * 0.48), "monthly_profit": int(monthly_profit_base * 0.75), "payback_months": 3},
            ],
            "requirements": ["كشف ذمم العملاء", "سياسة دفع واضحة", "قوالب رسائل متابعة", "مسؤول تحصيل بصلاحيات محددة"],
            "operating_model": ["تصنيف العملاء حسب التأخر", "إيقاف البيع الآجل للحسابات عالية المخاطر", "خصم دفع مبكر", "متابعة أسبوعية مع الإدارة"],
            "decision_gates": ["بعد 15 يوم: قياس نسبة الاستجابة", "بعد 30 يوم: مقارنة النقد المحصل بالهدف", "بعد 60 يوم: تحويل النقد المحصل لمخزون رابح"],
            "budget_breakdown": _budget_items(int(budget * 0.35), ["متابعة تحصيل", "خصومات دفع مبكر", "أتمتة رسائل", "احتياطي"]),
            "staffing": [{"role": "مسؤول تحصيل", "count": 1, "monthly_cost": 0, "responsibility": "متابعة العملاء والدفعات"}],
            "partners": [{"name": "شركات الدفع والتحويل", "type": "دفع", "relationship": "تحصيل أسرع", "reason": "تسريع دورة النقد"}],
            "implementation_plan": [
                {"phase": "30 يوم", "days": 30, "actions": ["تصنيف الذمم", "بدء رسائل التحصيل", "إيقاف التساهل مع الديون العالية"]},
                {"phase": "60 يوم", "days": 60, "actions": ["ربط التحصيل بالمبيعات", "مراجعة شروط البيع الآجل"]},
                {"phase": "90 يوم", "days": 90, "actions": ["إعادة تدوير النقد المحصل في المخزون الرابح"]},
            ],
            "marketing_plan": ["عروض دفع نقدي", "خصومات للعملاء الملتزمين"],
            "kpis": ["أيام التحصيل", "نسبة النقدي", "المتأخرات", "صافي التدفق النقدي"],
            "risks": ["انزعاج بعض العملاء من تشديد شروط الدفع"],
            "assumptions": ["الهدف تحسين التمويل الداخلي قبل المخاطرة بتوسع كبير"],
            "sources": [],
        },
        {
            "title": "شراكات توريد وتسويق لقناة بيع جديدة",
            "category": "شراكات",
            "fit_score": 76,
            "risk_level": "متوسط",
            "required_capital": int(budget * 0.65),
            "expected_monthly_revenue": int(budget * 0.58),
            "expected_monthly_profit": int(monthly_profit_base * 0.75),
            "payback_months": round((budget * 0.65) / (monthly_profit_base * 0.75), 1) if monthly_profit_base else None,
            "summary": "فتح قناة أو علاقة بيع جديدة مع ضبطها بسقف مالي واضح ومراجعة بعد 90 يوم.",
            "why_now": "تنويع الإيراد يقلل الاعتماد على قناة واحدة عندما تكون السيولة كافية.",
            "market_research": [
                "القناة الجديدة يجب أن تبدأ كتجربة قابلة للإيقاف وليس توسعاً ثابتاً.",
                "الاختبار الواقعي يحتاج رموز تتبع لكل شريك حتى لا تختلط مبيعات القنوات.",
                "الأولوية للشراكات التي تدفع على الأداء أو العمولة بدل مصاريف ثابتة عالية.",
            ],
            "financial_scenarios": [
                {"case": "محافظ", "monthly_revenue": int(budget * 0.30), "monthly_profit": int(monthly_profit_base * 0.40), "payback_months": 8},
                {"case": "متوقع", "monthly_revenue": int(budget * 0.58), "monthly_profit": int(monthly_profit_base * 0.75), "payback_months": round((budget * 0.65) / max(int(monthly_profit_base * 0.75), 1), 1) if budget else None},
                {"case": "متفائل", "monthly_revenue": int(budget * 0.82), "monthly_profit": int(monthly_profit_base * 1.05), "payback_months": round((budget * 0.65) / max(int(monthly_profit_base * 1.05), 1), 1) if budget else None},
            ],
            "requirements": ["اتفاق شراكة مكتوب", "رموز تتبع", "مسؤول متابعة", "مخزون منفصل للتجربة"],
            "operating_model": ["تشغيل شريكين فقط بالبداية", "قياس كل قناة أسبوعياً", "إيقاف الشريك غير المربح", "رفع الميزانية تدريجياً"],
            "decision_gates": ["بعد 21 يوم: إيقاف أي شريك لا يحقق طلبات", "بعد 45 يوم: رفع ميزانية الأفضل فقط", "بعد 90 يوم: تثبيت القناة أو إغلاقها"],
            "budget_breakdown": _budget_items(int(budget * 0.65), ["تجربة قناة", "محتوى وتصوير", "عمولات", "احتياطي"]),
            "staffing": [{"role": "منسق شراكات", "count": 1, "monthly_cost": 0, "responsibility": "إدارة العلاقات وقياس النتائج"}],
            "partners": [{"name": "قناة بيع/شركة تسويق محلية", "type": "تسويق", "relationship": "تجربة أداء", "reason": "توليد طلب جديد بسقف إنفاق محدد"}],
            "implementation_plan": [
                {"phase": "30 يوم", "days": 30, "actions": ["اختيار شريكين", "تجربة محدودة", "تحديد KPI"]},
                {"phase": "60 يوم", "days": 60, "actions": ["توسيع الشريك الأفضل", "إيقاف غير المجدي"]},
                {"phase": "90 يوم", "days": 90, "actions": ["قرار استمرار أو إغلاق التجربة"]},
            ],
            "marketing_plan": ["محتوى منتجات رابحة", "رموز خصم لكل شريك", "قياس تكلفة الطلب"],
            "kpis": ["طلبات القناة", "ربح القناة", "تكلفة الاكتساب", "نسبة الإرجاع"],
            "risks": ["جودة العملاء من القنوات الجديدة قد تكون أقل", "صعوبة القياس إن لم تستخدم رموز تتبع"],
            "assumptions": ["تبدأ كتجربة ولا تتحول لتوسع دائم إلا بعد تحقق الأرقام"],
            "sources": [],
        },
    ]
    proposals = _apply_project_scope(proposals, snapshot, top_page)
    scope = _normalize_project_scope(((snapshot.get("strategy") or {}).get("project_scope")))
    recommendation_reason = (
        "تم اختيار المقترح الأول لأنه يختبر الخروج من التخصص بأقل التزام ثابت وبمرحلة تحقق واضحة قبل التوسع."
        if scope == "outside"
        else "تم اختيار المقترح الأول لأنه يوازن بين قدرات الشركة الحالية وفرصة نمو قابلة للقياس مع إبقاء المخاطرة تحت السيطرة."
    )
    return {
        "strategy": snapshot.get("strategy") or {},
        "executive_summary": f"تم توليد خطة تقديرية محافظة من بيانات الشركة الحالية مع نطاق مشاريع: {PROJECT_SCOPE_OPTIONS[scope]['label']}، وسقف استثمار مبني على السيولة والالتزامات.",
        "financial_position": [
            f"السيولة الكلية: {_money(financial.get('total_liquidity')):,} د.ع",
            f"صافي ربح الفترة: {_money(financial.get('net_profit_period')):,} د.ع",
            f"سقف الاستثمار المقترح: {budget:,} د.ع",
        ],
        "proposals": proposals,
        "recommendation": {"selected_index": 0, "reason": recommendation_reason},
        "sources": [],
    }


def _normalize_proposal(item: dict, fallback: dict, budget: int) -> dict:
    data = {**fallback, **(item or {})}
    for key in ("required_capital", "expected_monthly_revenue", "expected_monthly_profit"):
        data[key] = max(_money(data.get(key)), 0)
    if budget and data["required_capital"] > int(budget * 1.2):
        data["required_capital"] = budget
    if data.get("payback_months") is None and data["expected_monthly_profit"]:
        data["payback_months"] = round(data["required_capital"] / data["expected_monthly_profit"], 1)
    data["fit_score"] = max(0, min(_money(data.get("fit_score")) or 70, 100))
    for list_key in (
        "budget_breakdown",
        "staffing",
        "partners",
        "implementation_plan",
        "marketing_plan",
        "kpis",
        "risks",
        "assumptions",
        "sources",
        "market_research",
        "financial_scenarios",
        "requirements",
        "operating_model",
        "decision_gates",
        "roi_logic",
        "funding_plan",
        "procurement_plan",
        "sales_channels",
        "control_points",
        "stop_loss_rules",
        "approval_requirements",
        "capability_gap",
        "validation_plan",
        "external_partners",
    ):
        if not isinstance(data.get(list_key), list):
            data[list_key] = fallback.get(list_key, [])
    data["is_outside_specialty"] = bool(data.get("is_outside_specialty"))
    data["outside_specialty_reason"] = _clip(data.get("outside_specialty_reason"), 900) or fallback.get("outside_specialty_reason", "")
    data["learning_cost"] = max(_money(data.get("learning_cost")), 0)
    return data


def _normalize_plan_payload(payload: dict | None, snapshot: dict, objective: str = "growth") -> dict:
    fallback = _fallback_plan(snapshot, objective)
    if not payload:
        sanitized, _ = sanitize_plan_numbers(fallback, snapshot)
        return sanitized
    budget = _money((snapshot.get("budget") or {}).get("recommended_budget"))
    proposals = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
    normalized = []
    for index in range(3):
        fallback_item = fallback["proposals"][index]
        normalized.append(_normalize_proposal(proposals[index] if index < len(proposals) else {}, fallback_item, budget))
    recommendation = payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else fallback["recommendation"]
    selected_index = max(0, min(_money(recommendation.get("selected_index")), 2))
    normalized_payload = {
        "strategy": payload.get("strategy") if isinstance(payload.get("strategy"), dict) else fallback.get("strategy", {}),
        "executive_summary": _clip(payload.get("executive_summary"), 1800) or fallback["executive_summary"],
        "financial_position": payload.get("financial_position") if isinstance(payload.get("financial_position"), list) else fallback["financial_position"],
        "proposals": normalized,
        "recommendation": {
            "selected_index": selected_index,
            "reason": _clip(recommendation.get("reason"), 1000) or fallback["recommendation"]["reason"],
        },
        "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
    }
    for key in ("board_brief", "funding_policy", "rejected_options", "governance"):
        if isinstance(payload.get(key), list):
            normalized_payload[key] = payload.get(key)
    sanitized, _ = sanitize_plan_numbers(normalized_payload, snapshot)
    return sanitized


def _get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("openai_api_key") or ""
    if key.strip():
        return key.strip()
    try:
        from flask import g
        from models.core.global_setting import GlobalSetting

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
        g.tenant = old_tenant
    except Exception:
        key = ""
    return key


def _investment_prompt(snapshot: dict, objective: str, external_research: bool) -> str:
    strategy = snapshot.get("strategy") or {}
    return (
        "أنت مستشار استثمارات كبير للشركات الصغيرة والمتوسطة في العراق. "
        "المطلوب خطة واقعية قابلة للتنفيذ وليست أفكار عامة. "
        "اعتمد على أرقام الشركة المرسلة ولا تخترع أرقاماً تاريخية غير موجودة. "
        "اقترح 3 مشاريع أو استثمارات قوية قابلة للمقارنة، واكتب JSON فقط. "
        "ابدأ بتحليل القدرة المالية قبل اقتراح المشاريع: صنف الشركة دفاعي/حذر/متوازن/هجومي محسوب، ثم اختر مشاريع تناسب هذا التصنيف. "
        f"نطاق المشاريع المطلوب: {strategy.get('project_scope_label') or 'محفظة مختلطة'} - {strategy.get('project_scope_description') or ''}. "
        "إذا كان النطاق mixed فيجب أن تحتوي المقترحات على مشروع قريب من النشاط، مشروع مجاور، ومشروع خارج التخصص كتجربة. "
        "إذا كان النطاق outside فيجب أن تكون المقترحات خارج تخصص الشركة الحالي، لكن كلها صغيرة ومرحلية. "
        "لا ترفض الخروج من التخصص بذاته؛ ارفض فقط الخروج الكبير بدون تجربة أو مصادر أو بوابات قرار. "
        "كل مبلغ بالدينار العراقي. يجب أن يحتوي JSON على: executive_summary, financial_position, board_brief, funding_policy, rejected_options, governance, proposals, recommendation, sources. "
        "كل proposal يجب أن يحتوي title, category, fit_score, risk_level, required_capital, expected_monthly_revenue, "
        "expected_monthly_profit, payback_months, summary, why_now, budget_breakdown, staffing, partners, "
        "market_research, financial_scenarios بثلاث حالات محافظة/متوقعة/متفائلة, requirements, operating_model, "
        "implementation_plan لمدد 30/60/90 يوم, marketing_plan, kpis, risks, decision_gates, assumptions, roi_logic, funding_plan, "
        "procurement_plan, sales_channels, control_points, stop_loss_rules, approval_requirements, is_outside_specialty, outside_specialty_reason, capability_gap, validation_plan, learning_cost, external_partners, sources. "
        "لا تقترح مشروعاً أكبر من قدرة الشركة؛ وإذا كانت القدرة ضعيفة اجعل المشاريع تحسين نقدية/تحصيل/مخزون بدل توسع كبير. "
        "اكتب أسباب رفض بدائل خطرة داخل rejected_options، واكتب سياسة صرف مرحلية داخل funding_policy. "
        "لا تجعل أي قسم قصيراً: summary لا يقل عن 60 كلمة، why_now لا يقل عن 40 كلمة، "
        "market_research لا يقل عن 5 نقاط، budget_breakdown لا يقل عن 6 بنود، staffing لا يقل عن 4 أدوار عند الحاجة، "
        "partners لا يقل عن 4 علاقات عملية، implementation_plan كل مرحلة لا تقل عن 5 إجراءات، "
        "marketing_plan لا يقل عن 6 إجراءات، kpis لا تقل عن 8 مؤشرات، risks لا تقل عن 6 مخاطر مع علاجها داخل النص إن أمكن. "
        "ضع أسباب الرفض أو الإيقاف بوضوح، وافصل الافتراضات عن الحقائق. "
        f"هدف الإدارة: {objective}. البحث الخارجي {'مفعل' if external_research else 'غير مفعل'}.\n\n"
        "بيانات الشركة:\n"
        + json.dumps(snapshot, ensure_ascii=False, default=str)
    )


def _call_openai_plan(snapshot: dict, objective: str, external_research: bool) -> tuple[dict | None, str | None]:
    key = _get_openai_key()
    if not key:
        return None, "OPENAI_API_KEY غير مضبوط."
    try:
        import openai
    except ImportError:
        return None, "مكتبة openai غير مثبتة."

    model = (
        os.environ.get("INVESTMENT_WEB_SEARCH_MODEL")
        if external_research
        else os.environ.get("INVESTMENT_AI_MODEL")
    ) or os.environ.get("FINORA_AI_MODEL") or os.environ.get("OPENAI_ANALYSIS_MODEL") or ("gpt-4.1-mini" if external_research else "gpt-4o-mini")
    prompt = _investment_prompt(snapshot, objective, external_research)
    ai_timeout = int(os.environ.get("INVESTMENT_WEB_SEARCH_TIMEOUT" if external_research else "INVESTMENT_AI_TIMEOUT") or (24 if external_research else 28))
    output_tokens = int(os.environ.get("INVESTMENT_AI_MAX_TOKENS") or (4500 if external_research else 5500))
    try:
        client = openai.OpenAI(api_key=key)
        if external_research and hasattr(client, "responses"):
            response = client.responses.create(
                model=model,
                tools=[{"type": "web_search"}],
                input=prompt,
                max_output_tokens=output_tokens,
                timeout=ai_timeout,
            )
            parsed = _json_from_text(getattr(response, "output_text", "") or "")
            if parsed:
                return parsed, None
            return None, "البحث الخارجي لم يرجع JSON صالح ضمن المهلة، تم اعتماد تحليل الشركة الداخلي."

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "أرجع JSON صالح فقط بدون Markdown."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=output_tokens,
            timeout=ai_timeout,
        )
        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice and choice.message else ""
        parsed = _json_from_text(text or "")
        if parsed:
            return parsed, None
        return None, "خدمة AI لم ترجع JSON صالح ضمن المهلة، تم اعتماد تحليل الشركة الداخلي."
    except Exception as exc:
        current_app.logger.warning("investment plan AI generation failed: %s", exc)
        return None, str(exc)


def _external_research_prompt(snapshot: dict, payload: dict, objective: str) -> str:
    lean_snapshot = {
        "company": snapshot.get("company"),
        "period": snapshot.get("period"),
        "investment_capacity": snapshot.get("investment_capacity"),
        "leaders": snapshot.get("leaders"),
        "financial": snapshot.get("financial"),
        "strategy": snapshot.get("strategy"),
    }
    current_proposals = [
        {
            "index": index,
            "title": item.get("title"),
            "category": item.get("category"),
            "required_capital": item.get("required_capital"),
            "expected_monthly_revenue": item.get("expected_monthly_revenue"),
            "expected_monthly_profit": item.get("expected_monthly_profit"),
        }
        for index, item in enumerate(payload.get("proposals") or [])
        if isinstance(item, dict)
    ]
    return (
        "أنت باحث سوق للشركات الصغيرة والمتوسطة في العراق. المطلوب إثراء خطة استثمار موجودة ببحث خارجي وروابط داعمة فقط، "
        "بدون تغيير أرقام رأس المال أو الأرباح لأن الأرقام مربوطة ببيانات الشركة. "
        "ارجع JSON صالح فقط يحتوي: external_summary, market_notes, sources, proposal_research. "
        "sources قائمة روابط فعلية قدر الإمكان وكل عنصر يحتوي title,url,note. "
        "proposal_research قائمة لكل مشروع وتحتوي index, market_research, partners, procurement_plan, sales_channels, risks, assumptions, external_partners, validation_plan. "
        "ركز أكثر على المشاريع خارج التخصص: مصادر، موردين، شركاء، منافسين، ومتطلبات تعلم وتشغيل، بدون تغيير الأرقام المالية. "
        "اكتب بالعربية، واذكر أن الروابط للقراءة والتحقق وليست ضماناً للسعر أو الربح. "
        f"هدف الإدارة: {objective}.\n\n"
        "بيانات الشركة المختصرة:\n"
        + json.dumps(lean_snapshot, ensure_ascii=False, default=str)
        + "\n\nالمقترحات الحالية:\n"
        + json.dumps(current_proposals, ensure_ascii=False, default=str)
    )


def _call_external_research(snapshot: dict, payload: dict, objective: str) -> tuple[dict | None, str | None]:
    key = _get_openai_key()
    if not key:
        return None, "OPENAI_API_KEY غير مضبوط."
    try:
        import openai
    except ImportError:
        return None, "مكتبة openai غير مثبتة."

    model = os.environ.get("INVESTMENT_WEB_SEARCH_MODEL") or os.environ.get("FINORA_AI_MODEL") or "gpt-4.1-mini"
    timeout = int(os.environ.get("INVESTMENT_BACKGROUND_RESEARCH_TIMEOUT") or 120)
    max_tokens = int(os.environ.get("INVESTMENT_RESEARCH_MAX_TOKENS") or 5000)
    prompt = _external_research_prompt(snapshot, payload, objective)
    try:
        client = openai.OpenAI(api_key=key)
        if hasattr(client, "responses"):
            last_error = None
            for tool_type in ("web_search_preview", "web_search"):
                try:
                    response = client.responses.create(
                        model=model,
                        tools=[{"type": tool_type}],
                        input=prompt,
                        max_output_tokens=max_tokens,
                        timeout=timeout,
                    )
                    parsed = _json_from_text(getattr(response, "output_text", "") or "")
                    if parsed:
                        return parsed, None
                    last_error = "البحث الخارجي لم يرجع JSON صالح."
                except Exception as exc:
                    last_error = str(exc)
                    continue
            return None, last_error or "فشل البحث الخارجي."

        return _call_openai_plan(snapshot, objective, False)
    except Exception as exc:
        current_app.logger.warning("investment external research failed: %s", exc)
        return None, str(exc)


def _append_unique(base: list, additions: list, limit: int = 12) -> list:
    result = list(base or [])
    seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item) for item in result}
    for item in additions or []:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
        if marker in seen:
            continue
        result.append(item)
        seen.add(marker)
        if len(result) >= limit:
            break
    return result


def _merge_external_research(payload: dict, research: dict) -> dict:
    merged = deepcopy(payload or {})
    merged["external_research"] = {
        "status": "completed",
        "summary": _clip(research.get("external_summary"), 1200),
        "market_notes": _ensure_list(research.get("market_notes"))[:12],
        "completed_at": datetime.utcnow().isoformat(),
    }
    merged["sources"] = _append_unique(_ensure_list(merged.get("sources")), _ensure_list(research.get("sources")), 18)
    proposals = merged.get("proposals") if isinstance(merged.get("proposals"), list) else []
    for row in _ensure_list(research.get("proposal_research")):
        if not isinstance(row, dict):
            continue
        if row.get("index") is None:
            continue
        index = _money(row.get("index"))
        if index < 0 or index >= len(proposals) or not isinstance(proposals[index], dict):
            continue
        proposal = proposals[index]
        for key in ("market_research", "partners", "procurement_plan", "sales_channels", "risks", "assumptions", "external_partners", "validation_plan", "capability_gap"):
            proposal[key] = _append_unique(_ensure_list(proposal.get(key)), _ensure_list(row.get(key)), 14)
    return merged


def enrich_investment_proposal_external_research(proposal_id: int) -> bool:
    proposal = db.session.get(InvestmentProposal, proposal_id)
    if not proposal:
        return False
    proposal.status = "research_running"
    db.session.commit()

    snapshot = proposal.get_financial_snapshot()
    payload = proposal.get_payload()
    research, error = _call_external_research(snapshot, payload, proposal.objective)
    if not research:
        proposal.status = "research_failed"
        proposal.error_message = error or "تعذر إكمال البحث الخارجي."
        db.session.commit()
        return False

    merged = _merge_external_research(payload, research)
    sanitized, _ = sanitize_plan_numbers(merged, snapshot)
    proposal.set_payload(sanitized)
    proposal.set_sources(sanitized.get("sources") or [])
    proposal.summary = sanitized.get("executive_summary") or proposal.summary
    proposal.status = "research_enriched"
    proposal.error_message = None
    proposal.external_research_enabled = True
    db.session.commit()
    return True


def create_investment_proposal(
    *,
    employee_id: int | None,
    period_type: str = "last_30_days",
    date_from: str | None = None,
    date_to: str | None = None,
    risk_profile: str = "balanced",
    objective: str = "growth",
    project_scope: str = "mixed",
    external_research: bool | None = None,
    use_ai: bool = True,
) -> InvestmentProposal:
    period_type = (period_type or "last_30_days").strip()
    risk_profile = (risk_profile or "balanced").strip()
    objective = (objective or "growth").strip()
    project_scope = _normalize_project_scope(project_scope)
    if external_research is None:
        external_research = (os.environ.get("INVESTMENT_EXTERNAL_RESEARCH") or "").strip() == "1"

    snapshot = collect_investment_context(period_type, date_from, date_to, risk_profile, project_scope)
    deferred_research = bool(external_research) and not use_ai
    ai_payload, ai_error = (None, None)
    if use_ai:
        ai_payload, ai_error = _call_openai_plan(snapshot, objective, bool(external_research))
    payload = _normalize_plan_payload(ai_payload, snapshot, objective)
    selected_index = _money((payload.get("recommendation") or {}).get("selected_index"))
    selected_index = max(0, min(selected_index, 2))
    title = f"خطة استثمارية - {snapshot.get('period', {}).get('label') or period_type}"
    proposal = InvestmentProposal(
        created_by_id=employee_id,
        period_type=period_type,
        risk_profile=risk_profile,
        objective=objective,
        external_research_enabled=bool(external_research),
        selected_index=selected_index,
        title=title,
        summary=payload.get("executive_summary"),
        status="research_pending" if deferred_research else ("generated" if not ai_error else "generated_with_fallback"),
        error_message=ai_error,
    )
    if snapshot.get("period", {}).get("date_from"):
        proposal.date_from = datetime.strptime(snapshot["period"]["date_from"], "%Y-%m-%d").date()
    if snapshot.get("period", {}).get("date_to"):
        proposal.date_to = datetime.strptime(snapshot["period"]["date_to"], "%Y-%m-%d").date()
    proposal.set_financial_snapshot(snapshot)
    proposal.set_payload(payload)
    proposal.set_sources(payload.get("sources") or [])
    db.session.add(proposal)
    db.session.flush()
    return proposal


def proposal_chart_payload(proposal: InvestmentProposal) -> dict:
    payload = proposal.get_payload()
    proposals = payload.get("proposals") or []
    return {
        "labels": [p.get("title") for p in proposals],
        "capital": [_money(p.get("required_capital")) for p in proposals],
        "profit": [_money(p.get("expected_monthly_profit")) for p in proposals],
        "revenue": [_money(p.get("expected_monthly_revenue")) for p in proposals],
    }
