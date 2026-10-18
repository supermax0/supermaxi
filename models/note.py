from datetime import datetime

from extensions import db


class Note(db.Model):
    """A private, tenant-local notebook entry owned by one employee."""

    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(200), nullable=False, default="ملاحظة جديدة")
    content = db.Column(db.Text, nullable=False, default="")
    plain_text = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(80), nullable=False, default="عام")
    tags_json = db.Column(db.Text, nullable=False, default="[]")
    color = db.Column(db.String(20), nullable=False, default="#7c3aed")
    priority = db.Column(db.String(20), nullable=False, default="normal")
    status = db.Column(db.String(20), nullable=False, default="active")
    is_pinned = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    due_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )

    owner = db.relationship("Employee", backref=db.backref("notes", lazy="dynamic"))
    revisions = db.relationship(
        "NoteRevision",
        back_populates="note",
        cascade="all, delete-orphan",
        order_by="NoteRevision.created_at.desc()",
    )


class NoteRevision(db.Model):
    """Small restore points created before meaningful note updates."""

    __tablename__ = "note_revisions"

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(
        db.Integer,
        db.ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    editor_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    note = db.relationship("Note", back_populates="revisions")
    editor = db.relationship("Employee")
