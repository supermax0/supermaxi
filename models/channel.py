# models/channel.py
from extensions import db
from datetime import datetime


class ChannelMessage(db.Model):
    """رسالة بث في قناة الإعلانات (يرسلها الأدمن للجميع)."""
    __tablename__ = "channel_message"

    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    content = db.Column(db.Text, nullable=True)

    file_type = db.Column(db.String(50), nullable=True)   # image, video, audio, file
    file_path = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)

    is_edited = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship(
        "Employee",
        foreign_keys=[sender_id],
        backref="channel_messages"
    )

    reads = db.relationship(
        "ChannelRead",
        backref="message",
        cascade="all, delete-orphan",
        lazy=True
    )

    def __repr__(self):
        return f"<ChannelMessage {self.id} | by {self.sender_id}>"

    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "sender_name": self.sender.name if self.sender else "",
            "content": self.content,
            "file_type": self.file_type,
            "file_path": self.file_path if self.file_path else None,
            "file_name": self.file_name,
            "is_edited": self.is_edited,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
        }


class ChannelRead(db.Model):
    """تتبّع قراءة كل موظف لرسائل القناة."""
    __tablename__ = "channel_read"

    id = db.Column(db.Integer, primary_key=True)

    channel_message_id = db.Column(
        db.Integer,
        db.ForeignKey("channel_message.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    read_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("channel_message_id", "user_id", name="_channel_read_uc"),
    )

    def __repr__(self):
        return f"<ChannelRead msg={self.channel_message_id} user={self.user_id}>"
