from __future__ import annotations

from datetime import datetime

from extensions import db


class Agent(db.Model):
    """تعريف Agent منطقي (شخصية الذكاء الاصطناعي) لكل مستأجر/مستخدم."""

    __tablename__ = "ai_agents"

    id = db.Column(db.Integer, primary_key=True)

    tenant_slug = db.Column(db.String(100), index=True, nullable=True)
    user_id = db.Column(db.Integer, index=True, nullable=True)

    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    default_model = db.Column(db.String(100), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "default_model": self.default_model,
            "instructions": self.instructions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentWorkflow(db.Model):
    """تعريف Workflow واحد تابع لـ Agent."""

    __tablename__ = "ai_agent_workflows"

    id = db.Column(db.Integer, primary_key=True)

    agent_id = db.Column(db.Integer, db.ForeignKey("ai_agents.id"), nullable=False, index=True)
    agent = db.relationship(Agent, backref=db.backref("workflows", lazy="dynamic"))

    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    # تمثيل الرسم (nodes / edges / settings) كـ JSON خام
    graph_json = db.Column(db.JSON, nullable=False, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "graph": self.graph_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentExecution(db.Model):
    """تشغيل واحد لWorkflow."""

    __tablename__ = "ai_agent_executions"

    id = db.Column(db.Integer, primary_key=True)

    workflow_id = db.Column(db.Integer, db.ForeignKey("ai_agent_workflows.id"), nullable=False, index=True)
    workflow = db.relationship(AgentWorkflow, backref=db.backref("executions", lazy="dynamic"))

    status = db.Column(db.String(20), default="running", nullable=False)  # running | success | failed
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)

    error_message = db.Column(db.Text, nullable=True)
    result_summary = db.Column(db.Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error_message": self.error_message,
            "result_summary": self.result_summary,
        }


class AgentExecutionLog(db.Model):
    """سجل خطوة تنفيذ لعقدة معينة داخل Execution."""

    __tablename__ = "ai_agent_execution_logs"

    id = db.Column(db.Integer, primary_key=True)

    execution_id = db.Column(db.Integer, db.ForeignKey("ai_agent_executions.id"), nullable=False, index=True)
    execution = db.relationship(AgentExecution, backref=db.backref("logs", lazy="dynamic"))

    node_id = db.Column(db.String(64), nullable=False)
    node_type = db.Column(db.String(50), nullable=False)

    status = db.Column(db.String(20), default="running", nullable=False)  # running | success | failed
    input_snapshot = db.Column(db.JSON, nullable=True)
    output_snapshot = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "status": self.status,
            "input": self.input_snapshot,
            "output": self.output_snapshot,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentComment(db.Model):
    """تعقب التعليقات التي تمت معالجتها بواسطة Agent."""

    __tablename__ = "ai_agent_comments"

    id = db.Column(db.Integer, primary_key=True)

    platform = db.Column(db.String(30), nullable=False)  # facebook | instagram | tiktok | ...
    account_id = db.Column(db.String(128), nullable=True)
    post_id = db.Column(db.String(128), nullable=True)
    comment_id = db.Column(db.String(128), nullable=True)

    author = db.Column(db.String(150), nullable=True)
    text = db.Column(db.Text, nullable=False)

    handled_by_execution_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_agent_executions.id"),
        nullable=True,
        index=True,
    )
    handled_execution = db.relationship(AgentExecution, backref=db.backref("handled_comments", lazy="dynamic"))

    reply_text = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="new", nullable=False)  # new | replied | skipped

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "account_id": self.account_id,
            "post_id": self.post_id,
            "comment_id": self.comment_id,
            "author": self.author,
            "text": self.text,
            "handled_by_execution_id": self.handled_by_execution_id,
            "reply_text": self.reply_text,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

