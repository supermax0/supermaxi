# models/system_analytics.py
from extensions import db
from datetime import datetime
import json

class SystemAnalytics(db.Model):
    """نموذج تحليلات النظام - يخزن التحليلات التلقائية"""
    __tablename__ = "system_analytics"

    id = db.Column(db.Integer, primary_key=True)
    
    # نوع التحليل
    analysis_type = db.Column(db.String(50), nullable=False)  # financial_error, inventory_alert, sales_trend, etc.
    
    # عنوان التحليل
    title = db.Column(db.String(200), nullable=False)
    
    # وصف مفصل
    description = db.Column(db.Text)
    
    # مستوى الأهمية
    severity = db.Column(db.String(20), default="info")  # critical, warning, info, success
    
    # البيانات المرتبطة (JSON)
    related_data = db.Column(db.Text)  # JSON string
    
    # حالة التحليل
    status = db.Column(db.String(20), default="active")  # active, resolved, dismissed
    
    # تمت معالجته
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    
    # الإحصائيات
    affected_count = db.Column(db.Integer, default=0)  # عدد السجلات المتأثرة
    estimated_impact = db.Column(db.Integer, default=0)  # التأثير المالي المقدر
    
    # الوقت
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """تحويل إلى dictionary"""
        return {
            "id": self.id,
            "analysis_type": self.analysis_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "is_resolved": self.is_resolved,
            "affected_count": self.affected_count,
            "estimated_impact": self.estimated_impact,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "related_data": json.loads(self.related_data) if self.related_data else None
        }
    
    def __repr__(self):
        return f"<SystemAnalytics {self.analysis_type} - {self.title}>"
