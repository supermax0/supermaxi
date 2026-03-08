# نموذج إشعار النشر التلقائي — يُخزّن في قاعدة بيانات الشركة (tenant)
from datetime import datetime
from extensions import db


class AutoposterNotification(db.Model):
    __tablename__ = "autoposter_notifications"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "read": self.read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
