"""Settings actions for authenticated FINORA operators; no secrets in reads or audit records."""
from __future__ import annotations

import jsonschema
from flask import jsonify, request

from .api import _actor, _json, finora_core_bp
from .auth import require
from .errors import validation_error
from .settings import CLOUD_KEY, apply_reply_policy, read_settings, reply_prompt, save_settings, settings_dto
from .store import audit, core_session, house_slug, set_setting, use_house


def _record(s, action: str, title: str):
    audit(s, actor=_actor(), actor_type="human", category="finora", action=action, title=title)


@finora_core_bp.get("/settings/agent")
@require("settings.manage")
def get_agent_settings():
    with core_session() as s:
        return jsonify(settings_dto(s))


@finora_core_bp.patch("/settings/agent")
@require("settings.manage")
def update_agent_settings():
    with core_session() as s:
        save_settings(s, _json(), _actor())
        _record(s, "settings.agent", "تحديث إعدادات ذكاء FINORA والردود")
        s.commit()
        return jsonify(settings_dto(s))


@finora_core_bp.post("/settings/agent/cloud-key")
@require("settings.manage")
def update_cloud_key():
    from modules.ai_sales.security import encrypt_secret

    data = _json()
    key = data.get("apiKey")
    if not isinstance(key, str) or (key and (not key.startswith("sk-") or len(key) < 20 or len(key) > 512
                                            or any(c.isspace() for c in key))):
        raise validation_error("مفتاح OpenAI غير صالح؛ اتركه فارغاً لاستخدام مفتاح الخادم")
    with core_session() as s:
        set_setting(s, CLOUD_KEY, encrypt_secret(key), _actor())
        _record(s, "settings.cloud_key", "تحديث مفتاح الذكاء السحابي")
        s.commit()
        return jsonify(settings_dto(s))


@finora_core_bp.post("/settings/agent/test")
@require("settings.manage")
def test_agent_provider():
    from .brain.provider import ProviderError, get_provider

    provider = get_provider()
    if provider is None:
        with core_session() as s:
            disabled = read_settings(s)["provider"] == "off"
        return jsonify({"ok": False, "message": "الذكاء متوقف؛ يعمل الرد بالقواعد الآمنة" if disabled else "مفتاح الذكاء السحابي غير مضبوط",
                        "provider": "rules", "model": ""})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    try:
        result = provider.generate_structured(system="Connection test. Return {\"ok\":true} only.",
                                              user="Test connection", schema=schema, schema_name="finora_connection_test")
        jsonschema.validate(result.data, schema)
        if result.data["ok"] is not True:
            raise ProviderError("invalid_json", "connection test failed")
    except (ProviderError, jsonschema.ValidationError) as exc:
        code = getattr(exc, "code", "invalid_json")
        return jsonify({"ok": False, "provider": provider.name, "model": "",
                        "message": f"فشل اختبار الاتصال ({code}). تحقق من المفتاح والنموذج وتشغيل الخدمة."})
    return jsonify({"ok": True, "provider": provider.name, "model": result.model,
                    "message": "الاتصال يعمل والنموذج أعاد إجابة صالحة"})


@finora_core_bp.post("/settings/agent/preview")
@require("settings.manage")
def preview_agent_reply():
    from .brain.extract import extract
    from .brain.knowledge import all_items, plan_prices, retrieve
    from .brain.planner import build_user_payload, plan_with_model, plan_with_rules, verify_plan
    from .brain.provider import ProviderError, get_provider

    text = _json().get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise validation_error("أدخل رسالة تجريبية لا تتجاوز 2000 حرف")
    text = text.strip()
    extraction = extract(text)
    with core_session() as s:
        config = read_settings(s)
        items = all_items(s)
        relevant = retrieve(items, text, limit=6)
        if "pricing" in extraction.intents:
            relevant += [i for i in items if i.category == "pricing" and i not in relevant]
        prices = plan_prices(s)
    plan_keys = {i.id.split(":", 1)[1] for i in items if i.id.startswith("plan:")}
    provider = get_provider()
    plan, fallback = None, None
    if provider is not None:
        try:
            plan = plan_with_model(provider, user_payload=build_user_payload(
                recent=[{"role": "customer", "text": text}], facts={}, lead_stage="new", knowledge=relevant,
                policy={"account_creation": "approval", "discount_limit_percent": 0}), style_prompt=reply_prompt(config))
        except ProviderError as exc:
            fallback = exc.code
    if plan is None:
        plan = plan_with_rules(extraction=extraction, text=text, facts={}, knowledge=relevant, plan_keys=plan_keys,
                               language=config["language"] if config["language"] != "auto" else None)
        fallback = fallback or ("rules_mode" if config["provider"] == "off" else "provider_unavailable")
    plan = verify_plan(plan, customer_text=text, extraction=extraction, knowledge=relevant,
                       plan_prices=prices, plan_keys=plan_keys)
    plan = apply_reply_policy(plan, config, extraction)
    return jsonify({"text": plan.reply_text, "source": plan.source, "model": plan.model,
                    "needsHuman": plan.needs_human, "reason": plan.handoff_reason, "fallback": fallback,
                    "knowledgeSources": [{"id": k.id, "title": k.title} for k in relevant if k.id in plan.cited]})


@finora_core_bp.get("/settings/knowledge")
@require("settings.manage")
def get_product_knowledge():
    from routes.superadmin import BUSINESS_TYPES
    from .brain.knowledge import all_items, retrieve
    from .brain.product_knowledge import coverage

    query = request.args.get("q", "").strip()
    business_type = request.args.get("businessType") or None
    if len(query) > 200 or (business_type and business_type not in BUSINESS_TYPES):
        raise validation_error("بحث المعرفة أو نوع النشاط غير صالح")
    with core_session() as s:
        items = all_items(s, business_type=business_type)
        result = coverage(items)
        result["results"] = [{"id": k.id, "title": k.title, "text": k.text.split("\n[", 1)[0],
                              "kind": "guide" if k.category == "tutorials" else "feature" if k.id.startswith("feature:") else "document",
                              "businessType": k.business_type, "source": k.source}
                             for k in retrieve(items, query, limit=8)] if query else []
    return jsonify(result)


@finora_core_bp.get("/settings/meta")
@require("settings.manage")
def get_meta_settings():
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.routes import _channel_webhook_url

    if house_slug() is None:
        return jsonify({"houseConfigured": False, "appId": "", "secretConfigured": False, "webhookUrl": "", "channels": []})
    with use_house():
        connector = AISalesChannelAccount.query.filter_by(channel_type="meta").first()
        channels = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(("instagram", "messenger"))).all()
        return jsonify({"houseConfigured": True, "appId": connector.external_account_id or "" if connector else "",
                        "secretConfigured": bool(connector and connector.app_secret_encrypted),
                        "webhookUrl": _channel_webhook_url(connector, house_slug(), request.host_url.rstrip("/")) if connector else "",
                        "channels": [{"type": c.channel_type, "name": c.name, "accountId": c.external_account_id or "",
                                      "status": c.connection_status or "unknown"} for c in channels]})


@finora_core_bp.post("/settings/meta/provision")
@require("settings.manage")
def provision_meta_house():
    from .meta_house import ActivationError, DEFAULT_HOUSE_SLUG, init_house_tenant

    existing = house_slug()
    try:
        slug = init_house_tenant(existing or DEFAULT_HOUSE_SLUG)
    except ActivationError:
        raise validation_error("تعذر تهيئة حساب FINORA الداخلي؛ تحقق من إعداد الخادم") from None
    with core_session() as s:
        set_setting(s, "house_tenant", slug, _actor())
        if not existing:
            # New channels start with proposals only, until the operator chooses automatic replies.
            set_setting(s, "flag:AI_SHADOW_MODE", "on", _actor())
            set_setting(s, "flag:AI_AUTO_REPLY", "off", _actor())
        _record(s, "settings.house", "تهيئة حساب FINORA الداخلي للقنوات")
        s.commit()
    return get_meta_settings()


@finora_core_bp.post("/settings/meta/connect")
@require("settings.manage")
def connect_meta_settings():
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.security import decrypt_secret
    from .meta_house import ActivationError, connect_meta

    data = _json()
    for name in ("appId", "appSecret", "userToken"):
        if not isinstance(data.get(name, ""), str) or len(data.get(name, "")) > 8192:
            raise validation_error("بيانات Meta غير صالحة")
    with use_house():
        connector = AISalesChannelAccount.query.filter_by(channel_type="meta").first()
        secret = data.get("appSecret", "").strip() or (decrypt_secret(connector.app_secret_encrypted) if connector else "")
    app_id = data.get("appId", "").strip()
    token = data.get("userToken", "").strip()
    if not app_id.isdigit() or not secret or not token:
        raise validation_error("أدخل App ID وApp Secret ورمز المستخدم الخاص بصفحات FINORA")
    try:
        report = connect_meta(app_id=app_id, app_secret=secret, user_token=token)
    except ActivationError:
        raise validation_error("رفض Meta الربط. تحقق من App ID وApp Secret وصلاحيات الرمز وإعداد Webhook") from None
    with core_session() as s:
        _record(s, "settings.meta_connect", "ربط صفحات FINORA بـ Meta")
        s.commit()
    # Graph warnings can contain credential-bearing URLs; return only a safe warning count.
    return jsonify({"pagesFound": report["pages_found"], "warningsCount": len(report["warnings"]),
                    "message": "تمت مزامنة الصفحات؛ افحص صحة القنوات للتأكد من الصلاحيات"})


@finora_core_bp.post("/settings/meta/verification")
@require("settings.manage")
def reveal_meta_verification():
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.security import decrypt_secret

    with use_house():
        connector = AISalesChannelAccount.query.filter_by(channel_type="meta").first()
        token = decrypt_secret(connector.verify_token_encrypted) if connector else ""
    if not token:
        raise validation_error("اربط تطبيق Meta أولاً")
    with core_session() as s:
        _record(s, "settings.meta_verification", "عرض رمز تحقق Webhook لمسؤول FINORA")
        s.commit()
    return jsonify({"verifyToken": token})
