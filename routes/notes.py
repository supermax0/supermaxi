from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session

from extensions import db
from models.note import Note, NoteRevision
from utils.activity_logger import log_activity
from utils.decorators import permission_required, permission_required_api
from utils.note_content import html_to_text, organize_plain_text, sanitize_note_html


notes_bp = Blueprint("notes", __name__, url_prefix="/notes")
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
VALID_STATUSES = {"active", "done"}
VALID_COLORS = {
    "#7c3aed", "#2563eb", "#0891b2", "#059669",
    "#ca8a04", "#ea580c", "#dc2626", "#db2777",
}


def _current_user_id() -> int:
    return int(session["user_id"])


def _owned_note(note_id: int) -> Note:
    return Note.query.filter_by(id=note_id, owner_id=_current_user_id()).first_or_404()


def _parse_due_at(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _clean_tags(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        tag = str(item or "").strip().lstrip("#")[:30]
        if tag and tag not in result:
            result.append(tag)
    return result[:12]


def _serialize(note: Note, *, include_content=True) -> dict:
    try:
        tags = json.loads(note.tags_json or "[]")
    except Exception:
        tags = []
    payload = {
        "id": note.id,
        "title": note.title,
        "excerpt": (note.plain_text or "")[:180],
        "category": note.category,
        "tags": tags,
        "color": note.color,
        "priority": note.priority,
        "status": note.status,
        "is_pinned": bool(note.is_pinned),
        "is_archived": bool(note.is_archived),
        "due_at": note.due_at.isoformat(timespec="minutes") if note.due_at else None,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "word_count": len((note.plain_text or "").split()),
    }
    if include_content:
        payload["content"] = note.content or ""
    return payload


@notes_bp.route("/")
@permission_required("use_notes")
def notebook():
    return render_template("notes/notebook.html")


@notes_bp.route("/api", methods=["GET"])
@permission_required_api("use_notes")
def list_notes():
    include_archived = request.args.get("archived") == "1"
    query = Note.query.filter_by(owner_id=_current_user_id(), is_archived=include_archived)
    notes = query.order_by(Note.is_pinned.desc(), Note.updated_at.desc()).all()
    return jsonify({"success": True, "notes": [_serialize(note, include_content=False) for note in notes]})


@notes_bp.route("/api", methods=["POST"])
@permission_required_api("use_notes")
def create_note():
    data = request.get_json(silent=True) or {}
    content = sanitize_note_html(data.get("content") or "<h2>فكرة جديدة</h2><p>ابدأ الكتابة هنا...</p>")
    note = Note(
        owner_id=_current_user_id(),
        title=str(data.get("title") or "ملاحظة جديدة").strip()[:200] or "ملاحظة جديدة",
        content=content,
        plain_text=html_to_text(content),
        category=str(data.get("category") or "عام").strip()[:80] or "عام",
        tags_json=json.dumps(_clean_tags(data.get("tags")), ensure_ascii=False),
        color=data.get("color") if data.get("color") in VALID_COLORS else "#7c3aed",
        priority=data.get("priority") if data.get("priority") in VALID_PRIORITIES else "normal",
        status="active",
    )
    db.session.add(note)
    db.session.commit()
    log_activity("create", "notes", f"إنشاء ملاحظة: {note.title}", entity_type="note", entity_id=note.id)
    return jsonify({"success": True, "note": _serialize(note)}), 201


@notes_bp.route("/api/<int:note_id>", methods=["GET"])
@permission_required_api("use_notes")
def get_note(note_id):
    return jsonify({"success": True, "note": _serialize(_owned_note(note_id))})


@notes_bp.route("/api/<int:note_id>", methods=["PUT"])
@permission_required_api("use_notes")
def update_note(note_id):
    note = _owned_note(note_id)
    data = request.get_json(silent=True) or {}
    old_content = note.content or ""
    old_title = note.title

    if "content" in data:
        note.content = sanitize_note_html(data.get("content"))
        note.plain_text = html_to_text(note.content)
    if "title" in data:
        note.title = str(data.get("title") or "").strip()[:200] or "ملاحظة بلا عنوان"
    if "category" in data:
        note.category = str(data.get("category") or "").strip()[:80] or "عام"
    if "tags" in data:
        note.tags_json = json.dumps(_clean_tags(data.get("tags")), ensure_ascii=False)
    if data.get("color") in VALID_COLORS:
        note.color = data["color"]
    if data.get("priority") in VALID_PRIORITIES:
        note.priority = data["priority"]
    if data.get("status") in VALID_STATUSES:
        note.status = data["status"]
    if "is_pinned" in data:
        note.is_pinned = bool(data["is_pinned"])
    if "is_archived" in data:
        note.is_archived = bool(data["is_archived"])
    if "due_at" in data:
        note.due_at = _parse_due_at(data.get("due_at"))

    if (old_content != note.content or old_title != note.title) and old_content:
        last_revision = (
            NoteRevision.query.filter_by(note_id=note.id)
            .order_by(NoteRevision.created_at.desc())
            .first()
        )
        if not last_revision or (datetime.utcnow() - last_revision.created_at).total_seconds() >= 300:
            db.session.add(
                NoteRevision(
                    note_id=note.id,
                    editor_id=_current_user_id(),
                    title=old_title,
                    content=old_content,
                )
            )

    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "note": _serialize(note)})


@notes_bp.route("/api/<int:note_id>", methods=["DELETE"])
@permission_required_api("use_notes")
def delete_note(note_id):
    note = _owned_note(note_id)
    title = note.title
    db.session.delete(note)
    db.session.commit()
    log_activity("delete", "notes", f"حذف ملاحظة: {title}", entity_type="note", entity_id=note_id)
    return jsonify({"success": True})


@notes_bp.route("/api/<int:note_id>/duplicate", methods=["POST"])
@permission_required_api("use_notes")
def duplicate_note(note_id):
    source = _owned_note(note_id)
    copy = Note(
        owner_id=_current_user_id(),
        title=f"نسخة من {source.title}"[:200],
        content=source.content,
        plain_text=source.plain_text,
        category=source.category,
        tags_json=source.tags_json,
        color=source.color,
        priority=source.priority,
    )
    db.session.add(copy)
    db.session.commit()
    return jsonify({"success": True, "note": _serialize(copy)}), 201


@notes_bp.route("/api/<int:note_id>/revisions", methods=["GET"])
@permission_required_api("use_notes")
def revisions(note_id):
    note = _owned_note(note_id)
    return jsonify({
        "success": True,
        "revisions": [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            }
            for row in note.revisions[:20]
        ],
    })


@notes_bp.route("/api/organize", methods=["POST"])
@permission_required_api("use_notes")
def organize():
    data = request.get_json(silent=True) or {}
    text = html_to_text(str(data.get("content") or ""))[:100_000]
    mode = data.get("mode") if data.get("mode") in {"organize", "tasks", "summary"} else "organize"
    result = sanitize_note_html(organize_plain_text(text, mode))
    return jsonify({"success": True, "content": result})
