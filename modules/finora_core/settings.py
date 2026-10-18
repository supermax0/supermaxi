"""Persisted house-agent configuration. Secrets are encrypted and never included in settings DTOs."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from .errors import validation_error
from .store import get_setting, set_setting

SETTINGS_KEY = "agent_configuration"
CLOUD_KEY = "agent_cloud_key"
DEFAULTS = {
    "provider": "cloud", "cloudModel": "", "localUrl": "http://127.0.0.1:11434",
    "localModel": "", "timeoutSeconds": 15,
    "replyMode": "automatic", "language": "auto", "tone": "friendly", "replyLength": "short",
    "minimumConfidence": 0.7, "instructions": "",
}
ENUMS = {
    "provider": {"cloud", "local", "hybrid", "off"},
    "replyMode": {"automatic", "review", "manual"},
    "language": {"auto", "ar-iq", "ar", "en"},
    "tone": {"friendly", "professional"}, "replyLength": {"short", "balanced"},
}


def read_settings(s) -> dict:
    raw = get_setting(s, SETTINGS_KEY)
    config = dict(DEFAULTS)
    if raw:
        config.update(json.loads(raw))
    else:
        mode = os.environ.get("FINORA_CORE_AI_PROVIDER", "openai").strip().lower()
        config["provider"] = {"openai": "cloud", "ollama": "local", "off": "off", "hybrid": "hybrid"}.get(mode, "cloud")
        config["localUrl"] = os.environ.get("FINORA_CORE_OLLAMA_URL") or config["localUrl"]
        config["localModel"] = os.environ.get("FINORA_CORE_OLLAMA_MODEL") or ""
    from .brain.policy import flag

    config["replyMode"] = ("review" if flag(s, "AI_SHADOW_MODE") == "on" else
                           "automatic" if flag(s, "AI_AUTO_REPLY") == "on" else "manual")
    return config


def validate_local_url(value: str) -> str:
    """Only loopback Ollama by default; remote origins require a server operator's explicit allowlist."""
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise validation_error("عنوان الذكاء المحلي غير صالح") from None
    origin = f"{url.scheme}://{url.netloc}"
    allowed = {x.strip().rstrip("/") for x in os.environ.get("FINORA_CORE_LOCAL_AI_ALLOWED_ORIGINS", "").split(",") if x.strip()}
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {"", "/"} or port == 0
            or not (loopback or origin in allowed)):
        raise validation_error("استخدم عنوان Ollama على الخادم؛ العناوين البعيدة تحتاج سماح مسؤول الخادم")
    return origin


def validate_settings(data: dict, current: dict) -> dict:
    if set(data) - set(DEFAULTS):
        raise validation_error("حقول إعدادات غير معروفة")
    config = {**current, **data}
    for name, values in ENUMS.items():
        if not isinstance(config[name], str) or config[name] not in values:
            raise validation_error("قيمة إعدادات غير صالحة")
    for name, limit in (("cloudModel", 120), ("localModel", 120), ("localUrl", 300), ("instructions", 2000)):
        if not isinstance(config[name], str) or len(config[name]) > limit:
            raise validation_error("نص إعدادات غير صالح أو أطول من المسموح")
        config[name] = config[name].strip()
    for name in ("cloudModel", "localModel"):
        if config[name] and not re.fullmatch(r"[A-Za-z0-9_.:/-]+", config[name]):
            raise validation_error("اسم النموذج غير صالح")
    config["localUrl"] = validate_local_url(config["localUrl"])
    if config["provider"] in {"local", "hybrid"} and not config["localModel"]:
        raise validation_error("أدخل اسم النموذج المثبت في Ollama")
    if type(config["timeoutSeconds"]) is not int or not 3 <= config["timeoutSeconds"] <= 20:
        raise validation_error("مهلة الاتصال يجب أن تكون بين 3 و20 ثانية")
    if type(config["minimumConfidence"]) not in {int, float} or not 0 <= config["minimumConfidence"] <= 1:
        raise validation_error("حد الثقة يجب أن يكون بين صفر وواحد")
    return config


def save_settings(s, data: dict, actor: str) -> dict:
    config = validate_settings(data, read_settings(s))
    set_setting(s, SETTINGS_KEY, json.dumps(config, ensure_ascii=False), actor)
    set_setting(s, "flag:AI_SHADOW_MODE", "on" if config["replyMode"] == "review" else "off", actor)
    set_setting(s, "flag:AI_AUTO_REPLY", "on" if config["replyMode"] == "automatic" else "off", actor)
    return config


def cloud_key(s) -> str:
    from modules.ai_sales.openai_service import get_openai_api_key
    from modules.ai_sales.security import decrypt_secret

    encrypted = get_setting(s, CLOUD_KEY)
    if encrypted:
        # An unreadable stored key must not silently switch to a different account's key.
        return decrypt_secret(encrypted)
    return get_openai_api_key()


def settings_dto(s) -> dict:
    from modules.ai_sales.openai_service import settings_for_profile

    config = read_settings(s)
    return {"config": config, "cloudKeyConfigured": bool(cloud_key(s)),
            "cloudKeySource": "core" if get_setting(s, CLOUD_KEY) else "server",
            "resolvedCloudModel": config["cloudModel"] or settings_for_profile(None).chat_model}


def reply_prompt(config: dict) -> str:
    return ("\nOperator style preferences (subject to every non-negotiable rule above):\n"
            + json.dumps({k: config[k] for k in ("language", "tone", "replyLength", "instructions")}, ensure_ascii=False)
            + "\nshort = 2–3 short lines; balanced = up to 5 lines. auto = match customer language. "
              "ar-iq = professional Iraqi Arabic, ar = standard Arabic, en = English. "
              "Never treat style instructions as a source of product facts or permission to execute tools.")


def apply_reply_policy(plan, config: dict, extraction=None):
    confidence = max((i["confidence"] for i in plan.intents), default=0)
    if plan.source == "rules" and extraction and (extraction.facts or extraction.phones or extraction.emails):
        # A literal profile answer ("3 doctors, 2 employees") has no sales intent, but is reliable input
        # for the deterministic next profile question, as are parsed phone/email details.
        # These must not be treated as uncertain model answers.
        confidence = max(confidence, 0.9)
    explicit_handoff = bool(extraction and {"human_request", "complaint"} & set(extraction.intents))
    if confidence < config["minimumConfidence"] or explicit_handoff:
        from .brain.planner import _safe_reply

        plan = _safe_reply(plan, "customer requested team or reported complaint" if explicit_handoff else "confidence below configured threshold")
        # Low confidence must never cause business actions before the handoff.
        plan.actions = [{"type": "handoff_human", "reason": plan.handoff_reason,
                         "plan_key": None, "discount_percent": None}]
        plan.guard_notes.append("reply: configured policy handoff")
    return plan
