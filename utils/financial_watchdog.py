# utils/financial_watchdog.py
"""
مراقب مالي / تشغيلي تلقائي (قواعد آمنة):
- تنبيهات فورية للوحة التحكم (بدون تعديل بيانات).
- حفظ اختياري في system_alert للمتابعة من واجهات أخرى (مع منع التكرار الزمني).
لا ينفّذ تحويلات مالية أو تغيير حالات طلبات تلقائياً — فقط إشعار واقتراح روابط.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from extensions import db
from models.invoice import Invoice
from models.system_alert import SystemAlert

# خفض الضغط على DB: لا نعيد كتابة تنبيهات المراقب إلا بعد هذه الثواني لكل مستأجر
_WATCHDOG_PERSIST_COOLDOWN_SEC = 4 * 3600
_last_persist_ts: dict[str, float] = {}


def _tenant_key() -> str:
    try:
        from flask import g, session

        return (getattr(g, "tenant", None) or session.get("tenant_slug") or "default").strip()
    except Exception:
        return "default"


def _recent_system_alert(alert_type: str, *, hours: float = 6) -> bool:
    since = datetime.utcnow() - timedelta(hours=hours)
    row = (
        SystemAlert.query.filter(
            SystemAlert.alert_type == alert_type,
            SystemAlert.created_at >= since,
            SystemAlert.is_dismissed.is_(False),
        )
        .first()
    )
    return row is not None


def _nav_decisions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    out = []
    for label, href in pairs:
        if label and href:
            out.append({"label": label, "href": href, "kind": "navigate"})
    return out


def get_watchdog_ephemeral_alerts() -> list[dict[str, Any]]:
    """
    تنبيهات تُدمج مع /api/index/alerts — محسوبة لحظياً (لا تعتمد على حفظ سابق).
    """
    alerts: list[dict[str, Any]] = []
    try:
        from ai.ai_utils import _snapshot_overdue_orders

        snap = _snapshot_overdue_orders()
    except Exception:
        snap = {"orders": [], "listed_count": 0, "critical_count": 0, "warning_only_count": 0}

    crit = int(snap.get("critical_count") or 0)
    warn_only = int(snap.get("warning_only_count") or 0)
    listed = int(snap.get("listed_count") or 0)

    if crit > 0:
        alerts.append(
            {
                "type": "danger",
                "icon": "🔴",
                "message": f"مراقب مالي: {crit} طلب(ات) حرجة (تأخير 10+ أيام) — إجمالي ظاهر في التحليل: {listed}.",
                "action": "/orders/",
                "source": "watchdog_overdue",
                "decisions": _nav_decisions(
                    ("عرض الطلبات", "/orders/"),
                    ("مساعد مالي (تحليل)", "/assistant/chat"),
                ),
            }
        )
    elif warn_only > 0:
        alerts.append(
            {
                "type": "warning",
                "icon": "🟠",
                "message": f"مراقب مالي: {warn_only} طلب(ات) متأخرة (7–9 أيام) — راجع التسليم.",
                "action": "/orders/",
                "source": "watchdog_overdue",
                "decisions": _nav_decisions(("عرض الطلبات", "/orders/"), ("مساعد مالي", "/assistant/chat")),
            }
        )

    try:
        pending = Invoice.query.filter(Invoice.status == "تم الطلب").count()
        shipping_stuck = (
            Invoice.query.filter(
                Invoice.status == "جاري الشحن",
                Invoice.created_at <= datetime.utcnow() - timedelta(days=5),
            ).count()
        )
    except Exception:
        pending, shipping_stuck = 0, 0

    if shipping_stuck >= 3:
        alerts.append(
            {
                "type": "warning",
                "icon": "🚚",
                "message": f"مراقب تشغيلي: {shipping_stuck} طلب «جاري الشحن» منذ 5+ أيام — قد تكون هناك اختناقة توصيل.",
                "action": "/orders/shipping",
                "source": "watchdog_shipping_stuck",
                "decisions": _nav_decisions(("شحن", "/orders/shipping"), ("كل الطلبات", "/orders/")),
            }
        )

    if pending >= 18:
        alerts.append(
            {
                "type": "info",
                "icon": "📋",
                "message": f"مراقب تشغيلي: {pending} طلب بحالة «تم الطلب» — راجع الأولوية والتجهيز.",
                "action": "/orders/ordered",
                "source": "watchdog_pending_backlog",
                "decisions": _nav_decisions(("طلبات جديدة", "/orders/ordered")),
            }
        )

    try:
        from utils.accounting_calculations import calculate_operational_profit, calculate_paid_sales

        paid = int(calculate_paid_sales() or 0)
        net = int(calculate_operational_profit() or 0)
        if paid > 500_000 and net < 0:
            alerts.append(
                {
                    "type": "danger",
                    "icon": "📉",
                    "message": "مراقب مالي: الربح التشغيلي سالب رغم وجود مبيعات مسددة — راجع التكاليف والمصاريف فوراً.",
                    "action": "/accounts",
                    "source": "watchdog_negative_operating",
                    "decisions": _nav_decisions(("الحسابات", "/accounts"), ("المصاريف", "/expenses")),
                }
            )
    except Exception:
        pass

    return alerts


def persist_watchdog_alerts() -> int:
    """
    يكتب تنبيهات system_alert للمستأجر الحالي (dedupe زمني).
    يُستدعى بحد أقصى كل بضع ساعات لكل مستأجر لتقليل الضجيج.
    """
    key = _tenant_key()
    now = time.time()
    if _last_persist_ts.get(key, 0) > now - _WATCHDOG_PERSIST_COOLDOWN_SEC:
        return 0

    inserted = 0
    try:
        try:
            from ai.ai_utils import _snapshot_overdue_orders

            snap = _snapshot_overdue_orders()
        except Exception:
            snap = {"listed_count": 0, "critical_count": 0, "warning_only_count": 0}

        crit = int(snap.get("critical_count") or 0)
        listed = int(snap.get("listed_count") or 0)
        warn_only = int(snap.get("warning_only_count") or 0)

        if listed > 0 and not _recent_system_alert("watchdog_overdue_digest", hours=5):
            pr = "high" if crit > 0 else "medium"
            msg = (
                f"طلبات متأخرة (تم الطلب/جاري الشحن): حرجة 10+ أيام = {crit}، "
                f"تحذير 7–9 أيام = {warn_only}، عيّنة في التحليل = {listed}. "
                f"راجع /orders/ أو المساعد المالي."
            )
            db.session.add(
                SystemAlert(
                    alert_type="watchdog_overdue_digest",
                    title="مراقب مالي — طلبات متأخرة",
                    message=msg,
                    priority=pr,
                    related_type="watchdog",
                    related_id=None,
                )
            )
            inserted += 1

        try:
            pending = Invoice.query.filter(Invoice.status == "تم الطلب").count()
            if pending >= 22 and not _recent_system_alert("watchdog_pending_digest", hours=8):
                db.session.add(
                    SystemAlert(
                        alert_type="watchdog_pending_digest",
                        title="مراقب تشغيلي — تراكم «تم الطلب»",
                        message=f"يوجد {pending} طلب بحالة تم الطلب. راجع /orders/ordered.",
                        priority="medium",
                        related_type="watchdog",
                        related_id=None,
                    )
                )
                inserted += 1
        except Exception:
            pass

        if inserted:
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0

    _last_persist_ts[key] = now
    return inserted
