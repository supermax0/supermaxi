# models/call.py
from extensions import db
from datetime import datetime


class CallSession(db.Model):
    """جلسة مكالمة فردية (1:1) صوت/فيديو بين موظفين."""
    __tablename__ = "call_session"

    id = db.Column(db.Integer, primary_key=True)

    caller_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )
    callee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    call_type = db.Column(db.String(10), default="audio")   # audio | video

    # ringing | accepted | rejected | ended | missed | canceled
    status = db.Column(db.String(20), default="ringing")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    caller = db.relationship("Employee", foreign_keys=[caller_id])
    callee = db.relationship("Employee", foreign_keys=[callee_id])

    signals = db.relationship(
        "CallSignal",
        backref="call",
        cascade="all, delete-orphan",
        lazy=True
    )

    def __repr__(self):
        return f"<CallSession {self.id} {self.caller_id}->{self.callee_id} {self.status}>"

    def peer_id(self, user_id):
        return self.callee_id if self.caller_id == user_id else self.caller_id

    def to_dict(self, user_id=None):
        peer = None
        peer_name = ""
        if user_id is not None:
            peer = self.peer_id(user_id)
            if peer == self.caller_id and self.caller:
                peer_name = self.caller.name
            elif peer == self.callee_id and self.callee:
                peer_name = self.callee.name
        return {
            "id": self.id,
            "caller_id": self.caller_id,
            "callee_id": self.callee_id,
            "caller_name": self.caller.name if self.caller else "",
            "callee_name": self.callee.name if self.callee else "",
            "call_type": self.call_type,
            "status": self.status,
            "peer_id": peer,
            "peer_name": peer_name,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
        }


class CallSignal(db.Model):
    """طابور إشارات WebRTC (offer/answer/ice/bye) يُقرأ تزايدياً عبر after_id."""
    __tablename__ = "call_signal"

    id = db.Column(db.Integer, primary_key=True)

    call_id = db.Column(
        db.Integer,
        db.ForeignKey("call_session.id"),
        nullable=False
    )

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    kind = db.Column(db.String(10), nullable=False)   # offer | answer | ice | bye

    payload = db.Column(db.Text, nullable=True)        # JSON string

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CallSignal {self.id} call={self.call_id} {self.kind}>"

    def to_dict(self):
        return {
            "id": self.id,
            "call_id": self.call_id,
            "sender_id": self.sender_id,
            "kind": self.kind,
            "payload": self.payload,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
        }
