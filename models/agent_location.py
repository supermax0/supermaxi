from datetime import datetime

from extensions import db


class DeliveryAgentPosition(db.Model):
    __tablename__ = "delivery_agent_position"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    accuracy = db.Column(db.Float, nullable=True)
    heading = db.Column(db.Float, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class DeliveryAgentTrail(db.Model):
    __tablename__ = "delivery_agent_trail"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, nullable=False, index=True)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
