# services/session_manager.py — FSM حجز تيليجرام (بدون dict في الذاكرة)
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from extensions import db
from models.telegram_booking_session import TelegramBookingSession

ASK_ADDRESS = "ASK_ADDRESS"
ASK_QUANTITY = "ASK_QUANTITY"
ASK_DATE = "ASK_DATE"
CONFIRM = "CONFIRM"


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")


def is_cancel_intent(text: str) -> bool:
    t = _norm(text)
    return any(
        x in t
        for x in ("الغاء", "الغي", "الغ", "cancel", "الغاء الطلب", "وقف", "stop")
    )


def is_confirm_intent(text: str) -> bool:
    t = _norm(text)
    return any(
        x in t
        for x in (
            "نعم",
            "نعم ",
            "تأكيد",
            "اكد",
            "أكد",
            "موافق",
            "تمام",
            "اوكي",
            "أوكي",
            "ok",
            "yes",
        )
    )


def _parse_positive_int(text: str) -> Optional[int]:
    raw = (text or "").strip()
    raw = raw.replace("٬", "").replace(",", "")
    m = re.search(r"\d+", raw)
    if not m:
        return None
    try:
        v = int(m.group(0))
        return v if v > 0 else None
    except ValueError:
        return None


def get_session(user_id: str, workflow_id: int) -> Optional[TelegramBookingSession]:
    return TelegramBookingSession.query.filter_by(
        user_id=str(user_id)[:64],
        workflow_id=int(workflow_id),
    ).first()


def reset_session(user_id: str, workflow_id: int) -> None:
    row = get_session(user_id, workflow_id)
    if row:
        db.session.delete(row)
        db.session.commit()


def handle_message(user_id: str, text: str, workflow_id: int, tenant_slug: Optional[str] = None) -> str:
    """
    يعالج رسالة واحدة ويعيد نص الرد للزبون.
    """
    uid = str(user_id)[:64]
    wf = int(workflow_id)
    ts = (tenant_slug or "").strip() or None
    raw = (text or "").strip()

    if is_cancel_intent(raw):
        reset_session(uid, wf)
        return "تم إلغاء الطلب. يمكنك البدء من جديد بأي رسالة."

    sess = get_session(uid, wf)

    if not sess:
        row = TelegramBookingSession(
            user_id=uid,
            workflow_id=wf,
            tenant_slug=ts,
            step=ASK_ADDRESS,
            updated_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return "مرحباً.\nأرسل عنوان التسليم (المنطقة / أقرب نقطة دالة)."

    # نية إلغاء في أي مرحلة (سبق التعامل أعلاه)

    if sess.step == ASK_ADDRESS:
        if len(raw) < 3:
            return "العنوان قصير جداً. أرسل عنواناً أوضح (حي، شارع، معلم)."
        sess.address = raw[:500]
        sess.step = ASK_QUANTITY
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        return "تم.\nكم الكمية المطلوبة؟ (رقم فقط، مثال: 2)"

    if sess.step == ASK_QUANTITY:
        q = _parse_positive_int(raw)
        if q is None:
            return "لم أفهم الكمية. أرسل رقماً صحيحاً أكبر من صفر (مثال: 1 أو 3)."
        sess.quantity = q
        sess.step = ASK_DATE
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        return "ما اليوم أو التاريخ المناسب للتسليم؟ (مثال: غداً، الخميس، 2026-04-05)"

    if sess.step == ASK_DATE:
        if len(raw) < 1:
            return "أرسل تاريخاً أو يوماً للتسليم."
        sess.date = raw[:100]
        sess.step = CONFIRM
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        summary = (
            "ملخص الطلب:\n"
            f"• العنوان: {sess.address}\n"
            f"• الكمية: {sess.quantity}\n"
            f"• التاريخ/اليوم: {sess.date}\n\n"
            "للتأكيد أرسل: نعم أو تأكيد\n"
            "للإلغاء أرسل: الغاء"
        )
        return summary

    if sess.step == CONFIRM:
        if is_confirm_intent(raw):
            reset_session(uid, wf)
            return "تم تأكيد الطلب وتسجيله. شكراً لك."
        if is_cancel_intent(raw):
            reset_session(uid, wf)
            return "تم إلغاء الطلب."
        return "أرسل «نعم» أو «تأكيد» لإتمام الطلب، أو «الغاء» للإلغاء."

    reset_session(uid, wf)
    return "حدث خطأ في الحالة. تمت إعادة التشغيل — أرسل رسالة من جديد."
