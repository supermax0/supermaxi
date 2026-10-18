"""Chat service: context → intent → registry-only response (validated). No DOM, no selectors, no raw HTML."""
from __future__ import annotations

import html
import logging
import re

from modules.ai_tutor import registry as tutorials
from modules.ai_tutor.chat import discovered
from modules.ai_tutor.chat import intent as intents
from modules.ai_tutor.chat import privacy
from modules.ai_tutor.chat.knowledge import Entry, Knowledge, load, ui_references
from modules.ai_tutor.chat.provider import NullProvider, ProviderError, TutorAIProvider
from modules.ai_tutor.facts import fact_met

log = logging.getLogger(__name__)

RESPONSE_TYPES = frozenset({"explanation", "tutorial_suggestion", "tutorial_started", "clarification", "not_found", "error"})
ACTION_TYPES = frozenset({"start_tutorial", "show_me", "show_current", "choose", "resume_dependency", "dismiss"})
MAX_MESSAGE_CHARS = 600
MAX_INPUT_CHARS = 300
ISSUES = frozenset({"target_missing", "validation_failed", "dependency_missing"})

# The three answers about a feature (spec): it does not exist / it exists but has no lesson / it has a lesson.
NOT_FOUND_TEXT = "ما لقيت هذه الميزة ضمن النسخة الحالية."
EXISTS_NO_LESSON_TEXT = "الميزة موجودة بالنظام، لكن الشرح التفاعلي الخاص بها بعده غير متوفر."
NO_PERMISSION_TEXT = "ما عندك صلاحية تنفيذ هذه العملية."
NO_REVERSAL_TEXT = "إلغاء الفاتورة أو عكس/حذف دفعة موجود خارج دروس التعليم الحالية."
NO_MEDICAL_TEXT = ("دوري هو تعليم استخدام Finora فقط، وما أكدر أعطي تشخيص أو علاج. "
                   "أكدر أعلمك وين تسجل التشخيص أو خطة العلاج داخل النظام.")


# ----------------------------------------------------------------- helpers

def _text(value: str) -> str:
    """Plain text only: tags removed, entities unescaped, whitespace collapsed, length capped."""
    cleaned = re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_MESSAGE_CHARS]


def _resp(kind: str, message: str, *, actions=None, tutorial_id=None, res: intents.Resolution | None = None, **meta) -> dict:
    return {
        "type": kind,
        "message": message,
        "tutorial_id": tutorial_id,
        "actions": actions or [],
        "meta": {"intent": res.intent if res else None, "confidence": round(res.confidence, 2) if res else 0,
                 "source": res.source if res else "none", "mode": res.mode if res else None, **meta},
    }


def _can_teach(entry: Entry, ctx: dict) -> bool:
    return bool(entry.tutorial) and entry.tutorial in ctx["available_tutorials"]


def _start_action(tutorial_id: str, label: str = "ابدأ التعليم") -> dict:
    return {"type": "start_tutorial", "label": label, "tutorial_id": tutorial_id}


def show_me_action(entry: Entry, ctx: dict, kb: Knowledge, label: str = "وريني وين") -> dict:
    """Visual guidance only: the on-page target when we are on the right page, otherwise the sidebar entry."""
    page = kb.pages[entry.page]
    if entry.target and ctx.get("page") == entry.page and discovered.is_discovered(entry.target):
        return {"type": "show_me", "label": label, "target": entry.target, "reveal": [],
                "message": f"{entry.title_ar}: هذا هو المكان."}  # a target the scan no longer finds falls back to the sidebar
    reveal = [{"action": "nav.menu.open"}]
    if page.nav_group:
        reveal.append({"section": f"nav.group.{page.nav_group}"})
    where = "أنت هنا" if ctx.get("page") == entry.page else f"هذا يكون ضمن «{page.title_ar}». اضغط عليه من القائمة."
    return {"type": "show_me", "label": label, "target": {"action": page.nav_action}, "reveal": reveal, "message": where}


def _quick_start_actions(ctx: dict, kb: Knowledge, limit: int = 3) -> list[dict]:
    seen, actions = set(), []
    for entry in kb.entries.values():
        if entry.kind == "feature" and entry.tutorial in ctx["available_tutorials"] and entry.tutorial not in seen:
            seen.add(entry.tutorial)
            actions.append(_start_action(entry.tutorial, entry.title_ar))
    return actions[:limit]


# ---------------------------------------------------------------- responders

def _feature_response(entry: Entry, res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    show = show_me_action(entry, ctx, kb)
    if entry.kind == "discovered":  # CASE 2 for analyzer-discovered features: where it is, never invented steps
        return _resp("explanation", f"الميزة موجودة في صفحة {kb.pages[entry.page].title_ar}. {EXISTS_NO_LESSON_TEXT}", actions=[show], res=res)
    if entry.tutorial == "payment.record" and (ctx.get("invoice_context") or {}).get("remaining") == 0:
        # The user is looking at a specific invoice (its own balance was shared, never its content) that already
        # has nothing owed on it: say so plainly and never offer to start the lesson on it.
        return _resp("explanation", "هاي الفاتورة مسددة بالكامل وما بيها مبلغ متبقٍ.", res=res)
    if entry.tutorial and not _can_teach(entry, ctx):
        reason = ctx.get("unavailable_reasons", {}).get(entry.tutorial)
        if reason == "permission":
            return _resp("explanation", NO_PERMISSION_TEXT, res=res)
        if reason and reason != "unavailable":
            # A real lesson that is not available in THIS tenant's setup (specialty/feature/page/context): say so
            # plainly, never invent steps and never offer to start it.
            text = entry.unavailable_ar or f"{entry.title_ar} غير متاحة في إعدادات هذه العيادة حالياً."
            return _resp("explanation", text, res=res)
    if res.mode == intents.MODE_SHOW_ME:
        actions = [show] + ([_start_action(entry.tutorial)] if _can_teach(entry, ctx) else [])
        return _resp("explanation", entry.explain_ar, actions=actions, tutorial_id=entry.tutorial if _can_teach(entry, ctx) else None, res=res)
    if res.mode == intents.MODE_EXPLAIN:
        actions = ([_start_action(entry.tutorial, "علمني عملياً")] if _can_teach(entry, ctx) else []) + [show]
        return _resp("explanation", entry.explain_ar, actions=actions, tutorial_id=entry.tutorial if _can_teach(entry, ctx) else None, res=res)
    if _can_teach(entry, ctx):
        return _resp("tutorial_suggestion", f"أكدر أعلمك {entry.title_ar} خطوة بخطوة.",
                     actions=[_start_action(entry.tutorial), show], tutorial_id=entry.tutorial, res=res)
    return _resp("explanation", f"{entry.explain_ar} {EXISTS_NO_LESSON_TEXT}", actions=[show], res=res)


def _page_entry_response(entry: Entry, res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    page = kb.pages[entry.page]
    here = ctx.get("page") == page.id
    text = f"{page.title_ar}: {page.summary_ar}"
    return _resp("explanation", ("أنت حالياً فيها. " if here else "") + text,
                 actions=[show_me_action(entry, ctx, kb)], res=res)


def _page_explain(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    page = kb.pages.get(ctx.get("page") or "")
    if not page:
        return _resp("explanation", "ما كدرت أحدد الصفحة الحالية. افتح صفحة من القائمة وأسألني عنها.",
                     actions=_quick_start_actions(ctx, kb), res=res)
    text = f"أنت حالياً بصفحة {page.title_ar}. {page.summary_ar}"
    features = [kb.entries[f] for f in page.feature_ids]
    if features:
        text += " من هنا تكدر: " + "، ".join(f.title_ar for f in features) + "."
    extra = [e.title_ar for e in kb.entries.values() if e.kind == "discovered" and e.page == page.id]
    if extra:
        text += " وفيها أيضاً: " + "، ".join(extra) + "."
    actions = [_start_action(f.tutorial, f.title_ar) for f in features if _can_teach(f, ctx)]
    return _resp("explanation", text, actions=actions, res=res)


def _active_step_message(ctx: dict) -> tuple[str, dict | None]:
    active = ctx.get("active_tutorial")
    if not active:
        return "", None
    definition = tutorials.get(active["id"])
    step = next((s for s in (definition or {}).get("steps", []) if s["id"] == active.get("step_id")), None)
    return ((step or {}).get("message_ar", ""), step)


def _active_help(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    message, step = _active_step_message(ctx)
    if not ctx.get("active_tutorial") or not message:
        return _resp("explanation", "ماكو درس شغال هسه. تحب نبدي درس؟", actions=_quick_start_actions(ctx, kb), res=res)
    return _resp("explanation", f"هسه: {message}", actions=[{"type": "show_current", "label": "وريني وين"}],
                 tutorial_id=ctx["active_tutorial"]["id"], res=res)


def _active_why(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    active = ctx.get("active_tutorial")
    issue = ctx.get("issue")
    if not active:
        return _resp("explanation", "ماكو درس شغال هسه. إذا واجهتك مشكلة بصفحة معينة اكتب اسمها وأشرحلك.",
                     actions=_quick_start_actions(ctx, kb), res=res)
    if issue == "dependency_missing":
        definition = tutorials.get(active["id"]) or {}
        dep = next((d for d in definition.get("dependencies", []) if not fact_met(d["fact"], ctx["facts"])), None)
        if dep:
            child = kb.entries.get(dep["tutorial"])
            title = child.title_ar if child else dep["tutorial"]
            actions = [{"type": "resume_dependency", "label": dep["action_label_ar"]}] if dep["tutorial"] in ctx["available_tutorials"] else []
            return _resp("explanation", f"ما نكدر نكمل لأن شرط أساسي ناقص: {dep['message_ar']} أقدر أفتحلك درس «{title}».",
                         actions=actions, tutorial_id=active["id"], res=res)
    if issue == "target_missing":
        return _resp("explanation", "ما كدرت ألقى العنصر المطلوب بهذه الصفحة. اضغط «العودة للخطوة السابقة» بالبطاقة، أو أنهِ الدرس وابدأه من جديد.",
                     tutorial_id=active["id"], res=res)
    if issue == "validation_failed":
        return _resp("explanation", "الحفظ ما نجح. راجع رسالة الخطأ الظاهرة بالنموذج (مثلاً اسم مستخدم مكرر أو بيان ناقص)، صححها وجرب «حفظ» من جديد.",
                     tutorial_id=active["id"], res=res)
    message, _ = _active_step_message(ctx)
    return _resp("explanation", f"لإكمال الدرس نحتاج منك هسه: {message}" if message else "كمّل الخطوة الظاهرة بالبطاقة وبعدها ننتقل للتالية.",
                 actions=[{"type": "show_current", "label": "وريني وين"}], tutorial_id=active["id"], res=res)


def _clarification(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    options = [kb.entries[c] for c, _ in res.candidates if c in kb.entries][:3]
    if len(options) >= 2:
        labels = [o.choice_ar or o.title_ar for o in options]
        question = "تقصد " + " لو ".join(labels) + "؟"
        actions = [{"type": "choose", "label": lab, "intent": o.id} for lab, o in zip(labels, options)]
    else:
        only = options[0]
        question = f"تقصد «{only.title_ar}»؟"
        actions = [{"type": "choose", "label": "نعم", "intent": only.id}, {"type": "dismiss", "label": "لا"}]
    return _resp("clarification", question, actions=actions, res=res)


def _not_found(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    text = NOT_FOUND_TEXT
    actions: list[dict] = []
    hint = kb.entries.get(res.candidates[0][0]) if res.candidates else None
    if hint:  # only reached for a clear near-miss
        text += f" أقرب شي لقيته: «{hint.title_ar}»."
        actions.append({"type": "choose", "label": hint.title_ar, "intent": hint.id})
    actions += _quick_start_actions(ctx, kb)
    return _resp("not_found", text, actions=actions[:4], res=res)


def _respond(res: intents.Resolution, ctx: dict, kb: Knowledge) -> dict:
    if res.intent is None:
        if res.confidence >= intents.CLARIFY and res.candidates:
            return _clarification(res, ctx, kb)
        return _not_found(res, ctx, kb)
    if res.intent == intents.META_PAGE:
        return _page_explain(res, ctx, kb)
    if res.intent == intents.META_ACTIVE_HELP:
        return _active_help(res, ctx, kb)
    if res.intent == intents.META_ACTIVE_WHY:
        return _active_why(res, ctx, kb)
    if res.intent == intents.META_NO_REVERSAL:
        # Void an invoice / reverse or delete a recorded payment: no real UI or backend workflow exists for
        # these yet, so refuse rather than invent one. Refund ("استرداد") is real and is handled as a normal
        # feature match against refund.record, never routed through this meta-intent.
        return _resp("explanation", NO_REVERSAL_TEXT, res=res)
    if res.intent == intents.META_MEDICAL:
        doctor_page = kb.entries["page:doctor"]
        return _resp("explanation", NO_MEDICAL_TEXT, actions=[show_me_action(doctor_page, ctx, kb, "وريني وين")], res=res)
    if res.intent == intents.META_GREETING:
        return _resp("explanation", "هلا بيك! أكدر أعلمك تستخدم Finora Clinics خطوة بخطوة. شنو تحب تتعلم؟",
                     actions=_quick_start_actions(ctx, kb), res=res)
    if res.intent == intents.META_THANKS:
        return _resp("explanation", "العفو! أي سؤال عن النظام أنا حاضر.", res=res)
    entry = kb.entries[res.intent]
    allowed = ctx.get("allowed_pages")
    if allowed is not None and entry.page not in allowed:  # never suggest what the user cannot do
        return _resp("explanation", NO_PERMISSION_TEXT, res=res)
    return (_page_entry_response if entry.kind == "page" else _feature_response)(entry, res, ctx, kb)


# --------------------------------------------------------------- validation

def _valid_ui_refs(kb: Knowledge) -> set[tuple]:
    return {tuple(sorted(ref.items())) for ref in ui_references()}


def validate_response(response: dict, ctx: dict, kb: Knowledge) -> dict:
    """Last line of defence: only registry things survive, text is plain, shape is the contract."""
    if response.get("type") not in RESPONSE_TYPES:
        return _resp("error", "تعذر تجهيز الجواب. جرب صياغة ثانية.")
    allowed_ui = _valid_ui_refs(kb)
    known = intents.known_ids(kb)
    clean_actions = []
    for action in response.get("actions", []):
        kind = action.get("type")
        if kind not in ACTION_TYPES or not _text(action.get("label")):
            continue
        item = {"type": kind, "label": _text(action["label"])[:40]}
        if kind == "start_tutorial":
            if action.get("tutorial_id") not in ctx["available_tutorials"]:
                continue
            item["tutorial_id"] = action["tutorial_id"]
        elif kind == "show_me":
            refs = [action.get("target"), *action.get("reveal", [])]
            if not all(isinstance(r, dict) and tuple(sorted(r.items())) in allowed_ui for r in refs if r is not None):
                continue
            item.update(target=action["target"], reveal=action.get("reveal", []), message=_text(action.get("message")))
        elif kind == "choose":
            if action.get("intent") not in known:
                continue
            item["intent"] = action["intent"]
        clean_actions.append(item)
    tutorial_id = response.get("tutorial_id")
    if tutorial_id is not None and tutorial_id not in tutorials.load_all():
        tutorial_id = None
    message = _text(response.get("message"))
    if not message:
        return _resp("error", "تعذر تجهيز الجواب. جرب صياغة ثانية.")
    return {"type": response["type"], "message": message, "tutorial_id": tutorial_id,
            "actions": clean_actions, "meta": response.get("meta", {})}


# ------------------------------------------------------------------- public

def _ai_resolution(message: str, ctx: dict, provider: TutorAIProvider, kb: Knowledge) -> intents.Resolution | None:
    """Optional LLM classification: only for unclear messages, only registry ids are accepted."""
    if isinstance(provider, NullProvider) or not privacy.allow_llm(message):
        return None
    try:
        answer = provider.classify_intent(privacy.build_llm_payload(message, ctx, kb))
    except ProviderError as exc:
        log.warning("AI Tutor provider failed, using deterministic result: %s", exc)
        return None
    if not isinstance(answer, dict):
        return None
    try:
        confidence = float(answer.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    chosen = answer.get("intent")
    if chosen in kb.entries and confidence >= intents.CLARIFY:
        return intents.Resolution(chosen, min(confidence, 0.95), intents.MODE_GUIDE, "ai", [(chosen, confidence)])
    candidates = [c for c in (answer.get("candidates") or []) if c in kb.entries]
    if len(candidates) >= 2:
        return intents.Resolution(None, intents.CLARIFY, intents.MODE_GUIDE, "ai", [(c, confidence) for c in candidates[:3]])
    return None  # unknown id or low confidence: never trusted


def answer(message: str, ctx: dict, *, forced_intent: str | None = None, provider: TutorAIProvider | None = None) -> dict:
    kb = load()
    provider = provider or NullProvider()
    text = (message or "").strip()[:MAX_INPUT_CHARS]
    if forced_intent is not None:
        if forced_intent not in kb.entries:
            return validate_response(_resp("error", "اختيار غير معروف."), ctx, kb)
        res = intents.Resolution(forced_intent, 1.0, intents.MODE_GUIDE, "choice", [(forced_intent, 1.0)])
    elif not text:
        return validate_response(_resp("clarification", "اكتب سؤالك عن استخدام النظام، مثلاً: شلون أضيف طبيب؟", actions=_quick_start_actions(ctx, kb)), ctx, kb)
    else:
        res = intents.resolve(text, kb)
        if (res.intent is None or res.confidence < intents.CONFIDENT) and not res.is_meta:
            ai = _ai_resolution(text, ctx, provider, kb)
            if ai:
                res = ai
    return validate_response(_respond(res, ctx, kb), ctx, kb)
