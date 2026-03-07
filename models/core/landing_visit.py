# models/core/landing_visit.py — عدّاد زيارات صفحة الهبوط (قاعدة Core فقط)
from extensions import db
from datetime import datetime, date
import json


def _today_iso():
    return date.today().isoformat()


class LandingVisit(db.Model):
    """
    سجل واحد في قاعدة Core لحفظ إجمالي زيارات صفحة الهبوط وزيارات اليوم.
    لا يعتمد على أي جدول خاص بالشركات (tenant) ليعمل مع Core DB فقط.
    """
    __tablename__ = "landing_visits"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    total_count = db.Column(db.Integer, default=0, nullable=False)
    # زيارات يومية بصيغة JSON: {"daily": {"2025-03-03": 12, "2025-03-02": 8}}
    daily_json = db.Column(db.Text, default="{}", nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    RECORD_ID = 1

    @classmethod
    def get_or_create(cls):
        row = cls.query.get(cls.RECORD_ID)
        if row is None:
            row = cls(id=cls.RECORD_ID, total_count=0, daily_json="{}")
            db.session.add(row)
            db.session.commit()
            row = cls.query.get(cls.RECORD_ID)
        return row

    @classmethod
    def increment(cls):
        """زيادة العدّاد (إجمالي + تاريخ اليوم)."""
        row = cls.get_or_create()
        row.total_count = (row.total_count or 0) + 1
        today = _today_iso()
        try:
            data = json.loads(row.daily_json or "{}")
        except Exception:
            data = {}
        daily = data.get("daily", {})
        daily[today] = int(daily.get(today, 0)) + 1
        data["daily"] = daily
        row.daily_json = json.dumps(data)
        db.session.commit()

    @classmethod
    def get_today_count(cls):
        today = _today_iso()
        row = cls.query.get(cls.RECORD_ID)
        if not row or not row.daily_json:
            return 0
        try:
            data = json.loads(row.daily_json)
            return int(data.get("daily", {}).get(today, 0))
        except Exception:
            return 0
