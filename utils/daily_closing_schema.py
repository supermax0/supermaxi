"""Idempotent schema/permission setup for existing tenant databases."""

import weakref
from datetime import datetime

from extensions import db
from models.daily_closing import (
    DailyCashAdjustment,
    DailyClosingAuditLog,
    DailyClosingSnapshotHistory,
    DailyInventoryCount,
    DailySession,
    InventoryCountTemplate,
    InventoryCountTemplateItem,
)

_ready = weakref.WeakSet()

PERMISSIONS = {
    "daily_report.view": "عرض التقرير اليومي",
    "daily_report.create": "بدء يومية جديدة",
    "daily_report.edit": "تعديل اليومية المفتوحة",
    "daily_report.close": "إغلاق اليومية",
    "daily_report.reopen": "إعادة فتح اليومية",
    "daily_report.print": "طباعة التقرير اليومي",
    "daily_report.export": "تنزيل التقرير اليومي",
    "daily_report.inventory_count": "تنفيذ الجرد اليومي",
    "daily_report.override_variance": "تجاوز فروقات الإغلاق",
}


def ensure_daily_closing_schema() -> None:
    bind = db.session.get_bind()
    if bind not in _ready:
        for model in (
            DailySession,
            DailyInventoryCount,
            InventoryCountTemplate,
            InventoryCountTemplateItem,
            DailyCashAdjustment,
            DailyClosingAuditLog,
            DailyClosingSnapshotHistory,
        ):
            model.__table__.create(bind=bind, checkfirst=True)
        _ready.add(bind)

    from models.role import Permission

    changed = False
    for name, description in PERMISSIONS.items():
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=description, created_at=datetime.utcnow()))
            changed = True
    if changed:
        db.session.commit()
