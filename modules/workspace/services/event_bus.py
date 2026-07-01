from __future__ import annotations

import queue
import threading
from typing import Any, Dict, List, Optional

from extensions import db

from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent


_subscribers: Dict[str, List[queue.Queue]] = {}
_sub_lock = threading.Lock()


def _get_subscribers(session_id: str) -> List[queue.Queue]:
    with _sub_lock:
        return list(_subscribers.get(session_id, []))


def subscribe(session_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=256)
    with _sub_lock:
        _subscribers.setdefault(session_id, []).append(q)
    return q


def unsubscribe(session_id: str, q: queue.Queue) -> None:
    with _sub_lock:
        subs = _subscribers.get(session_id, [])
        if q in subs:
            subs.remove(q)
        if not subs and session_id in _subscribers:
            del _subscribers[session_id]


def emit_event(
    session_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    user_id: Optional[int] = None,
) -> WorkspaceAuditEvent:
    event = WorkspaceAuditEvent(
        session_id=session_id,
        event_type=event_type,
        message=message,
        user_id=user_id,
    )
    event.set_payload(payload or {})
    db.session.add(event)
    db.session.commit()

    sse_data = event.to_sse_dict()
    for q in _get_subscribers(session_id):
        try:
            q.put_nowait(sse_data)
        except queue.Full:
            pass

    return event


def replay_events(session_id: str, after_id: int = 0):
    query = WorkspaceAuditEvent.query.filter_by(session_id=session_id)
    if after_id > 0:
        query = query.filter(WorkspaceAuditEvent.id > after_id)
    return query.order_by(WorkspaceAuditEvent.id.asc()).all()
