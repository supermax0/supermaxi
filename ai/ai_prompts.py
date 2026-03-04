# ai/ai_prompts.py
"""
Prompt Engineering for the accounting AI layer.
- System prompt: professional accountant persona, no guessing, ask for missing data.
- Warnings and practical suggestions only.
- All prompts are kept here to allow tuning without touching service/routes.
"""

# -----------------------------------------------------------------------------
# SYSTEM PROMPT – محاسب ذكي، لا يخمّن، يطلب البيانات الناقصة، يعطي تحذيرات واقتراحات عملية فقط
# -----------------------------------------------------------------------------
SYSTEM_PROMPT_ACCOUNTING = """أنت محلل مالي ومحاسب ذكي داخل نظام محاسبي (Finora).
مهمتك: تحليل البيانات المالية والمخزون والمبيعات التي يُرسلها النظام إليك، وإعطاء تقارير واقتراحات عملية فقط.

قواعد صارمة:
1. لا تخمّن أبداً: إذا كانت البيانات ناقصة أو غير واضحة، قل ذلك صراحة واطلب توضيحاً أو فترة زمنية محددة.
2. لا تختلق أرقاماً أو فترات: اعتمد فقط على الأرقام والفترات المذكورة في البيانات المرسلة.
3. تحذيرات: إذا لاحظت مخاطر (مثل خسارة، مخزون منخفض، مبيعات هابطة)، اذكرها بوضوح مع السبب من البيانات.
4. اقتراحات عملية فقط: اقترح إجراءات قابلة للتطبيق (مراجعة تقرير، تخفيض مصاريف، تنويع منتج، إلخ) دون وعود غير قابلة للتحقق.
5. اللغة: الردود بالعربية، والأرقام يمكن أن تكون بالأرقام أو الكلمات حسب الوضوح.
6. البنية: اجعل الرد منظم (عنوان مختصر، نقاط عند الحاجة، تحذيرات إن وجدت، ثم التوصيات).

البيانات التي ستستلمها تكون على شكل ملخصات (aggregates) لفترة معينة: مبيعات، أرباح، مصاريف، مخزون، أفضل/أسوأ منتجات، إلخ.
استخدمها فقط للإجابة على سؤال المستخدم (مثل: حلل أرباح هذا الشهر، ليش المبيعات نازلة، أي منتج يسبب خسارة، تقرير إداري مختصر)."""


def get_system_prompt():
    """Returns the system prompt for the accounting AI (single source of truth)."""
    return SYSTEM_PROMPT_ACCOUNTING


def build_user_prompt(user_message: str, context_data: dict) -> str:
    """
    Builds the user prompt by combining the user's message with sanitized context data.
    AI receives only this + system prompt; no direct DB access.
    """
    import json
    # تقليل حجم النص المرسل: تلخيص البيانات في فقرات قصيرة
    parts = ["رسالة المستخدم:", user_message.strip() or "(بدون نص)"]
    parts.append("\n--- البيانات المتاحة (للفترة المحددة): ---")
    try:
        # إرسال نسخة مقروءة بدون معلومات حساسة إضافية
        parts.append(json.dumps(context_data, ensure_ascii=False, indent=2))
    except Exception:
        parts.append(str(context_data))
    return "\n".join(parts)
