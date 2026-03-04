# models/assistant_memory.py
from extensions import db
from datetime import datetime
import json

class AssistantMemory(db.Model):
    """ذاكرة المساعد - يتعلم من الأخطاء والأنماط"""
    __tablename__ = "assistant_memory"

    id = db.Column(db.Integer, primary_key=True)
    
    # نوع الذاكرة
    memory_type = db.Column(db.String(50), nullable=False)  # pattern, error_fix, prediction, etc.
    
    # المفتاح (مثل: invoice_id, product_id, pattern_name)
    memory_key = db.Column(db.String(200), nullable=False)
    
    # القيمة (JSON)
    memory_value = db.Column(db.Text)  # JSON string
    
    # الإحصائيات
    occurrence_count = db.Column(db.Integer, default=1)  # عدد مرات الحدوث
    last_occurrence = db.Column(db.DateTime, default=datetime.utcnow)
    first_occurrence = db.Column(db.DateTime, default=datetime.utcnow)
    
    # الثقة (0-100)
    confidence = db.Column(db.Float, default=50.0)
    
    # تم التحقق منه
    is_verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    
    # الوقت
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """تحويل إلى dictionary"""
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "memory_key": self.memory_key,
            "memory_value": json.loads(self.memory_value) if self.memory_value else None,
            "occurrence_count": self.occurrence_count,
            "confidence": self.confidence,
            "is_verified": self.is_verified,
            "last_occurrence": self.last_occurrence.isoformat() if self.last_occurrence else None
        }
    
    def __repr__(self):
        return f"<AssistantMemory {self.memory_type} - {self.memory_key}>"
