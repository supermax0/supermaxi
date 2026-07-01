from __future__ import annotations

import json
import queue

from flask import Blueprint, Response, current_app, g, jsonify, request, session, stream_with_context

from modules.workspace.services import event_bus
from modules.workspace.services.session_service import SessionService

stream_api_bp = Blueprint("workspace_stream_api", __name__)


def _ctx():
    return {
        "user_id": session.get("user_id"),
        "tenant_slug": session.get("tenant_slug") or getattr(g, "tenant", None),
    }


@stream_api_bp.route("/sessions/<session_id>/stream")
def stream_session(session_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    ctx = _ctx()
    ws = SessionService.get_session(
        session_id,
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404

    last_event_id = (
        request.headers.get("Last-Event-ID")
        or request.args.get("since")
        or request.args.get("after", "0")
    )
    try:
        after_id = int(last_event_id)
    except (TypeError, ValueError):
        after_id = 0

    def generate():
        try:
            for ev in event_bus.replay_events(session_id, after_id):
                data = json.dumps(ev.to_sse_dict(), ensure_ascii=False)
                yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {data}\n\n"
        except Exception as exc:
            current_app.logger.error("Workspace SSE replay failed: %s", exc)
            err = json.dumps(
                {"type": "stream.error", "message": "تعذّر تحميل سجل الأحداث"},
                ensure_ascii=False,
            )
            yield f"event: stream.error\ndata: {err}\n\n"
            return

        q = event_bus.subscribe(session_id)
        try:
            heartbeat = 0
            while True:
                try:
                    item = q.get(timeout=15)
                    eid = item.get("event_id", "")
                    etype = item.get("type", "message")
                    data = json.dumps(item, ensure_ascii=False)
                    yield f"id: {eid}\nevent: {etype}\ndata: {data}\n\n"
                    if etype in (
                        "session.completed",
                        "session.cancelled",
                        "workflow.completed",
                    ):
                        break
                except queue.Empty:
                    heartbeat += 1
                    yield f": heartbeat {heartbeat}\n\n"
                    if heartbeat > 120:
                        break
        finally:
            event_bus.unsubscribe(session_id, q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
