"""Prepare editable, platform-aware ad copy for installment products."""
from __future__ import annotations

import json
import os
from typing import Any

from flask import current_app


PLATFORM_CONFIG = {
    "facebook": {
        "label": "فيسبوك",
        "launch_url": "https://adsmanager.facebook.com/adsmanager/creation/",
        "hint": "إعلان بصورة أو فيديو مع نص واضح وزر طلب الآن.",
    },
    "instagram": {
        "label": "إنستغرام",
        "launch_url": "https://adsmanager.facebook.com/adsmanager/creation/",
        "hint": "نص بصري مختصر مناسب للمنشورات والريلز والستوري.",
    },
    "google": {
        "label": "Google Ads",
        "launch_url": "https://ads.google.com/",
        "hint": "عناوين وأوصاف وكلمات بحث جاهزة لحملة Google Ads.",
    },
    "tiktok": {
        "label": "تيك توك",
        "launch_url": "https://ads.tiktok.com/business/",
        "hint": "افتتاحية سريعة وسيناريو قصير مناسب للفيديو العمودي.",
    },
}


AD_CREATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "primary_text": {"type": "string"},
        "headline": {"type": "string"},
        "description": {"type": "string"},
        "call_to_action": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "search_headlines": {"type": "array", "items": {"type": "string"}},
        "search_descriptions": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "video_hook": {"type": "string"},
        "video_script": {"type": "string"},
        "visual_direction": {"type": "string"},
    },
    "required": [
        "primary_text", "headline", "description", "call_to_action", "hashtags",
        "search_headlines", "search_descriptions", "keywords", "video_hook",
        "video_script", "visual_direction",
    ],
}


def _fallback_creative(product: dict[str, Any], platform: str) -> dict[str, Any]:
    title = str(product.get("title") or "المنتج")
    price = int(product.get("cash_price") or 0)
    price_text = f"بسعر نقدي {price:,} د.ع" if price else "بسعر مناسب"
    months = int(product.get("max_months") or 0)
    installment_text = f" وتقسيط لغاية {months} شهر" if months else ""
    link = str(product.get("store_url") or "")
    text = f"خلّي {title} أقرب إلك! {price_text}{installment_text}. اطّلع على التفاصيل وقدّم طلبك الآن."
    if link:
        text += f"\n{link}"
    keywords = [value for value in (title, product.get("category"), "تقسيط العراق", "أجهزة منزلية") if value]
    return {
        "primary_text": text,
        "headline": f"{title} بالتقسيط",
        "description": "دفعات مريحة وتفاصيل واضحة قبل تقديم الطلب.",
        "call_to_action": "تسوّق الآن",
        "hashtags": ["#تقسيط", "#العراق", "#تسوق_الآن"],
        "search_headlines": [f"اشترِ {title}", f"{title} بالتقسيط", "قدّم طلبك الآن"],
        "search_descriptions": [text[:90], "خطط دفع مريحة مع متابعة واضحة للطلب."],
        "keywords": keywords[:8],
        "video_hook": f"تدور على {title} بدفعات مريحة؟",
        "video_script": f"اعرض المنتج من أكثر من زاوية، ثم السعر وخيارات التقسيط، واختم بدعوة لفتح الرابط وتقديم الطلب.",
        "visual_direction": "ابدأ بأوضح صورة، ثم المواصفات والسعر، واستخدم الفيديو كخاتمة إذا كان متوفرًا.",
        "platform": platform,
        "ai_generated": False,
    }


def generate_ad_creative(
    product: dict[str, Any],
    *,
    platform: str,
    objective: str = "sales",
    tone: str = "iraqi",
    media_summary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate factual ad copy, with a deterministic editable fallback."""
    if platform not in PLATFORM_CONFIG:
        raise ValueError("منصة الإعلان غير مدعومة")
    fallback = _fallback_creative(product, platform)
    try:
        from modules.ai_sales.openai_service import get_openai_api_key, get_openai_client

        if not get_openai_api_key():
            fallback["warning"] = "مفتاح الذكاء الاصطناعي غير مضبوط؛ تم تجهيز نص قابل للتعديل."
            return fallback

        selected_model = str(
            current_app.config.get("INSTALLMENT_AD_MODEL")
            or os.environ.get("FINORA_AD_MODEL")
            or "gpt-5.6-sol"
        ).strip()
        facts = {
            "platform": platform,
            "platform_guidance": PLATFORM_CONFIG[platform]["hint"],
            "objective": objective,
            "tone": tone,
            "product": product,
            "selected_media": media_summary or [],
        }
        response = get_openai_client().responses.create(
            model=selected_model,
            instructions=(
                "أنت كاتب إعلانات لمتجر عراقي. أنشئ كليشة عربية طبيعية ومقنعة ومناسبة للمنصة المحددة. "
                "التزم حرفياً بحقائق المنتج المرسلة ولا تخترع خصماً أو ضماناً أو توصيلاً أو مواصفة غير موجودة. "
                "اكتب باللهجة العراقية الخفيفة من دون مبالغة، واجعل الناتج جاهزاً للمراجعة قبل النشر. "
                "لعناوين Google اجعل كل عنوان قصيراً، ولتيك توك اجعل الافتتاحية سريعة والفيديو عمودياً."
            ),
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(facts, ensure_ascii=False)}],
            }],
            text={"format": {"type": "json_schema", "name": "installment_ad_creative", "strict": True, "schema": AD_CREATIVE_SCHEMA}},
            reasoning={"effort": "low"},
            max_output_tokens=2200,
            store=False,
        )
        raw = str(getattr(response, "output_text", "") or "").strip()
        creative = json.loads(raw)
        store_url = str(product.get("store_url") or "").strip()
        if store_url and store_url not in str(creative.get("primary_text") or ""):
            creative["primary_text"] = f"{str(creative.get('primary_text') or '').rstrip()}\n{store_url}".strip()
        creative.update({"platform": platform, "ai_generated": True, "model": selected_model})
        return creative
    except Exception as exc:  # The editor must remain usable during provider outages.
        current_app.logger.warning("Installment ad copy generation failed: %s", exc)
        fallback["warning"] = "تعذّر الاتصال بالذكاء الاصطناعي حالياً؛ تم تجهيز نص بديل قابل للتعديل."
        return fallback
