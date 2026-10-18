"""Per-user training progress (tenant DB). Never stores field contents."""
from datetime import datetime

from extensions import db

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_PAUSED = "paused"
PROGRESS_STATUSES = (STATUS_NOT_STARTED, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_PAUSED)


class UserTrainingProgress(db.Model):
    __tablename__ = "user_training_progress"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "user_id", "tutorial_id", name="uq_user_training_progress"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    tutorial_id = db.Column(db.String(80), nullable=False)
    tutorial_version = db.Column(db.Integer, nullable=False, default=1)
    current_step = db.Column(db.String(80), nullable=True)
    step_index = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default=STATUS_NOT_STARTED)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Set while this run was started as a dependency of a parent tutorial (resume the parent afterwards).
    parent_tutorial_id = db.Column(db.String(80), nullable=True)
    parent_step_id = db.Column(db.String(80), nullable=True)


class TrainingActivityLog(db.Model):
    __tablename__ = "training_activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    tutorial_id = db.Column(db.String(80), nullable=False, index=True)
    tutorial_version = db.Column(db.Integer, nullable=False, default=1)
    step_id = db.Column(db.String(80), nullable=True)
    event = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


AI_TUTOR_MODELS = (UserTrainingProgress, TrainingActivityLog)
