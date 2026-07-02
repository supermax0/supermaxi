import json
from datetime import datetime

from extensions import db


class FixedAssetAuditLog(db.Model):
    """سجل تدقيق عمليات الأصول الثابتة."""

    __tablename__ = "fixed_asset_audit_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=True, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("fixed_asset.id"), nullable=True, index=True)
    summary = db.Column(db.Text, nullable=False)
    old_values_json = db.Column(db.Text, nullable=True)
    new_values_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("Employee", foreign_keys=[user_id], lazy=True)
    asset = db.relationship("FixedAsset", foreign_keys=[asset_id], lazy=True)

    def get_old_values(self):
        return self._parse_json(self.old_values_json)

    def get_new_values(self):
        return self._parse_json(self.new_values_json)

    @staticmethod
    def _parse_json(raw):
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_old_values(self, data):
        self.old_values_json = json.dumps(data or {}, ensure_ascii=False)

    def set_new_values(self, data):
        self.new_values_json = json.dumps(data or {}, ensure_ascii=False)

    def action_label(self):
        labels = {
            "create": "إنشاء أصل",
            "update": "تعديل أصل",
            "post_acquisition": "ترحيل شراء",
            "post_depreciation": "ترحيل استهلاك",
            "maintenance": "صيانة",
            "capital_improvement": "تحسين رأسمالي",
            "transfer": "نقل أصل",
            "sale": "بيع أصل",
            "scrap": "إتلاف أصل",
            "settings_update": "تحديث إعدادات",
            "status_change": "تغيير حالة",
            "disposal_request": "طلب بيع/إتلاف",
            "disposal_approved": "موافقة بيع/إتلاف",
            "disposal_rejected": "رفض بيع/إتلاف",
            "period_close": "إغلاق فترة",
            "period_reopen": "إعادة فتح فترة",
            "attachment_upload": "رفع مرفق",
            "attachment_delete": "حذف مرفق",
        }
        return labels.get(self.action, self.action)
