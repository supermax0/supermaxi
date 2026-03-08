# نموذج صفحة فيسبوك للنشر التلقائي — يُخزّن في قاعدة بيانات الشركة (tenant)
from datetime import datetime
from extensions import db


class AutoposterFacebookPage(db.Model):
    __tablename__ = "autoposter_facebook_pages"

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.String(64), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    access_token = db.Column(db.String(512), nullable=False)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.page_id,
            "name": self.name,
            "status": "connected" if self.access_token else "token_expired",
        }
