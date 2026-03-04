# models/message.py
from extensions import db
from datetime import datetime


class Message(db.Model):
    __tablename__ = "message"

    id = db.Column(db.Integer, primary_key=True)
    
    # المرسل والمستقبل
    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )
    
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )
    
    # محتوى الرسالة
    content = db.Column(db.Text, nullable=True)
    
    # الملفات المرفقة
    file_type = db.Column(db.String(50), nullable=True)  # image, video, audio, file
    file_path = db.Column(db.String(500), nullable=True)  # مسار الملف
    file_name = db.Column(db.String(255), nullable=True)  # اسم الملف الأصلي
    
    # حالة الرسالة
    is_read = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)
    
    # الوقت
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
    # العلاقات
    sender = db.relationship(
        "Employee",
        foreign_keys=[sender_id],
        backref="sent_messages"
    )
    
    receiver = db.relationship(
        "Employee",
        foreign_keys=[receiver_id],
        backref="received_messages"
    )
    
    def __repr__(self):
        return f"<Message {self.id} | {self.sender_id} -> {self.receiver_id}>"
    
    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "sender_name": self.sender.name if self.sender else "",
            "receiver_id": self.receiver_id,
            "receiver_name": self.receiver.name if self.receiver else "",
            "content": self.content,
            "file_type": self.file_type,
            "file_path": self.file_path if self.file_path else None,
            "file_name": self.file_name,
            "is_read": self.is_read,
            "is_edited": self.is_edited,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
            "time_ago": self.get_time_ago()
        }
    
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

