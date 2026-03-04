# ai/ai_service.py
"""
AI service layer: orchestrates analysis requests.
- Resolves type (sales / profit / inventory / report) and period.
- Collects data via ai_utils.collect_context_data (no direct DB access from this module).
- Builds prompts from ai_prompts, calls OpenAI via ai_utils.call_openai.
- Returns structured JSON for the dashboard (analysis text, suggestions, warnings).
"""

import logging
from typing import Any, Optional

from ai.ai_prompts import get_system_prompt, build_user_prompt
from ai import ai_utils

logger = logging.getLogger("ai_layer")


def analyze(
    analyze_type: str,
    period: str,
    message: str = "",
    custom_date_from: Optional[str] = None,
    custom_date_to: Optional[str] = None,
) -> dict:
    """
    Runs the full analysis pipeline. Call from route only (needs Flask app context for data collection).
    Returns dict with: success, analysis (text), error (if not success), and optional suggestions/warnings
    parsed from the response (for future use; currently we return the full text as analysis).
    """
    # 1) Validate
    ok, err = ai_utils.validate_analyze_params(
        analyze_type, period, custom_date_from, custom_date_to
    )
    if not ok:
        return {"success": False, "error": err, "analysis": None}

    # 2) Collect context (requires app context)
    try:
        context_data = ai_utils.collect_context_data(
            period.strip().lower(),
            custom_date_from=custom_date_from,
            custom_date_to=custom_date_to,
        )
    except Exception as e:
        logger.exception("Data collection failed: %s", e)
        return {
            "success": False,
            "error": "فشل تجميع البيانات. تأكد من الفترة والمتغيرات.",
            "analysis": None,
        }

    # 3) Build messages
    system_prompt = get_system_prompt()
    user_prompt = build_user_prompt(message or _default_message_for_type(analyze_type), context_data)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 4) Call OpenAI
    success, text = ai_utils.call_openai(messages)
    if not success:
        return {"success": False, "error": text, "analysis": None}

    # 5) Return formatted result for dashboard
    return {
        "success": True,
        "analysis": text,
        "error": None,
        "period_label": context_data.get("period_label"),
    }


def _default_message_for_type(analyze_type: str) -> str:
    """Default user message when none provided, based on type (use cases from spec)."""
    defaults = {
        "sales": "حلل المبيعات لهذه الفترة ولماذا قد تكون نازلة أو صاعدة.",
        "profit": "حلل أرباح هذه الفترة.",
        "inventory": "ما المنتجات التي تسبب خسارة أو مخزون منخفض؟",
        "report": "سوي تقرير إداري مختصر للفترة.",
    }
    return defaults.get(analyze_type.strip().lower(), "اعطني تحليل مختصر للبيانات المعروضة.")
