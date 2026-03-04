# models/agent_message.py
from extensions import db
from datetime import datetime

class AgentMessage(db.Model):
    __tablename__ = "agent_message"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # المرسل
    sender_id = db.Column(db.Integer, nullable=False)  # يمكن أن يكون agent_id أو employee_id
    sender_type = db.Column(db.String(20), nullable=False)  # "agent" أو "employee"
    sender_name = db.Column(db.String(100), nullable=True)  # اسم المرسل (للحفظ)
    
    # المستقبل
    receiver_id = db.Column(db.Integer, nullable=False)  # يمكن أن يكون agent_id أو employee_id
    receiver_type = db.Column(db.String(20), nullable=False)  # "agent" أو "employee"
    receiver_name = db.Column(db.String(100), nullable=True)  # اسم المستقبل (للحفظ)
    
    # محتوى الرسالة
    content = db.Column(db.Text, nullable=False)
    
    # حالة الرسالة
    is_read = db.Column(db.Boolean, default=False)
    
    # الوقت
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<AgentMessage {self.id} | {self.sender_type}:{self.sender_id} -> {self.receiver_type}:{self.receiver_id}>"
    
    def get_time_ago(self):
        if not self.created_at:
            return ""
        
        now = datetime.utcnow()
        diff = now - self.created_at
        
        if diff.total_seconds() < 60:
            return "الآن"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() / 60)
            return f"منذ {minutes} دقيقة"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() / 3600)
            return f"منذ {hours} ساعة"
        else:
            days = int(diff.total_seconds() / 86400)
            return f"منذ {days} يوم"
