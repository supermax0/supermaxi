from datetime import datetime

from flask import Blueprint, jsonify, request, session

from extensions import db
from models.employee import Employee
from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation
from modules.facebook_routing.engine import (
    FACEBOOK_CHANNELS,
    _active_count,
    _state,
    can_manage_routing,
    can_transfer,
    can_use_inbox,
    conversation_for_psid,
    drain_unassigned_queue,
    page_key,
    transfer_conversation,
)
from modules.facebook_routing.models import FacebookEmployeeRouting, FacebookPageEmployee, FacebookPageRouting
from modules.facebook_routing.schema import ensure_facebook_routing_schema
from utils.permission_checks import get_current_employee

facebook_routing_bp = Blueprint(
    "facebook_routing",
    __name__,
    template_folder="../../templates",
)


@facebook_routing_bp.before_request
def _ensure_ai_sales_schema_for_routing():
    # Reads ai_sales_channel_account directly; make sure columns added to
    # that model (e.g. the TikTok fields) exist before queries run here.
    from modules.ai_sales.schema import ensure_ai_sales_schema

    ensure_ai_sales_schema()


def _channels_for_routing():
    """Distribution must list every page that has a saved token, not only old channels."""
    from modules.facebook_monitor.webhook import sync_messenger_channel
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token

    channels = (
        AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(tuple(FACEBOOK_CHANNELS)))
        .order_by(AISalesChannelAccount.name.asc())
        .all()
    )
    known = {str(channel.page_id or "") for channel in channels if channel.page_id}
    try:
        stored = PublisherPage.query.filter(PublisherPage.page_token.isnot(None)).all()
    except Exception:
        stored = []
    dirty = False
    for row in stored:
        pid = str(row.page_id or "").strip()
        if not pid or pid in known:
            continue
        token = decrypt_token(row.page_token or "")
        if not token:
            continue
        sync_messenger_channel(
            page_id=pid,
            page_name=row.page_name or pid,
            page_token=token,
        )
        known.add(pid)
        dirty = True
    if dirty:
        db.session.commit()
        channels = (
            AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(tuple(FACEBOOK_CHANNELS)))
            .order_by(AISalesChannelAccount.name.asc())
            .all()
        )
    return channels


def _actor():
    employee = get_current_employee()
    is_admin = bool(session.get("is_superadmin") or session.get("role") == "admin" or (employee and employee.role == "admin"))
    return employee, is_admin


@facebook_routing_bp.get("/api/facebook-routing/config")
def get_config():
    employee, is_admin = _actor()
    if not can_manage_routing(employee, is_admin=is_admin):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ensure_facebook_routing_schema()
    channels = _channels_for_routing()
    staff = Employee.query.filter_by(is_active=True).order_by(Employee.name.asc()).all()
    pages = []
    seen = set()
    for channel in channels:
        pid = page_key(channel)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        routing = FacebookPageRouting.query.filter_by(page_id=pid).first()
        links = FacebookPageEmployee.query.filter_by(page_id=pid).all()
        waiting = AISalesConversation.query.filter(
            AISalesConversation.channel_account_id == channel.id,
            AISalesConversation.assigned_employee_id.is_(None),
            AISalesConversation.status != "closed",
        ).count()
        pages.append({
            "page_id": pid,
            "name": channel.name,
            "channel_id": channel.id,
            "routing_enabled": bool(routing.routing_enabled) if routing else False,
            "default_max": (routing.default_max_conversations if routing else 10),
            "reply_timeout_minutes": int((getattr(routing, "reply_timeout_seconds", None) or 180) / 60),
            "waiting": waiting,
            "employees": [
                {
                    "employee_id": link.employee_id,
                    "enabled": bool(link.is_enabled),
                    "max_active": link.max_active_conversations,
                    "active": _active_count(link.employee_id),
                }
                for link in links
            ],
        })
    people = []
    for row in staff:
        state = _state(row.id)
        people.append({
            "id": row.id,
            "name": row.name,
            "accept_messages": bool(state.accept_messages),
            "presence": state.presence,
            "active": _active_count(row.id),
            "max_active": state.max_active_conversations or 10,
            "reply_timeout_minutes": int((state.reply_timeout_seconds or 180) / 60),
            "can_inbox": can_use_inbox(row),
        })
    return jsonify({"ok": True, "pages": pages, "employees": people})


@facebook_routing_bp.post("/api/facebook-routing/pages")
def save_page():
    employee, is_admin = _actor()
    if not can_manage_routing(employee, is_admin=is_admin):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ensure_facebook_routing_schema()
    data = request.get_json(silent=True) or {}
    page_id = str(data.get("page_id") or "").strip()
    if not page_id:
        return jsonify({"ok": False, "error": "صفحة غير معروفة"}), 400
    routing = FacebookPageRouting.query.filter_by(page_id=page_id).first()
    if not routing:
        routing = FacebookPageRouting(page_id=page_id)
        db.session.add(routing)
    routing.channel_account_id = data.get("channel_id") or routing.channel_account_id
    routing.routing_enabled = bool(data.get("routing_enabled"))
    routing.routing_method = "LEAST_ACTIVE" if routing.routing_enabled else "MANUAL_OFF"
    routing.default_max_conversations = max(1, min(50, int(data.get("default_max") or 10)))
    if data.get("reply_timeout_minutes") not in (None, ""):
        routing.reply_timeout_seconds = max(60, min(3600, int(data.get("reply_timeout_minutes") or 3) * 60))
    wanted = {int(row.get("employee_id")): row for row in (data.get("employees") or []) if row.get("employee_id")}
    existing = {link.employee_id: link for link in FacebookPageEmployee.query.filter_by(page_id=page_id).all()}
    for emp_id, payload in wanted.items():
        link = existing.pop(emp_id, None)
        if not link:
            link = FacebookPageEmployee(page_id=page_id, employee_id=emp_id)
            db.session.add(link)
        link.is_enabled = bool(payload.get("enabled", True))
        cap = payload.get("max_active")
        if cap not in (None, ""):
            try:
                cap_n = max(1, min(80, int(cap)))
            except (TypeError, ValueError):
                cap_n = None
        else:
            cap_n = None
        link.max_active_conversations = cap_n
        if cap_n:
            _state(emp_id).max_active_conversations = cap_n
        timeout_minutes = payload.get("reply_timeout_minutes")
        if timeout_minutes not in (None, ""):
            try:
                _state(emp_id).reply_timeout_seconds = max(60, min(3600, int(timeout_minutes) * 60))
            except (TypeError, ValueError):
                pass
    for leftover in existing.values():
        leftover.is_enabled = False
    db.session.commit()
    if routing.routing_enabled:
        drain_unassigned_queue(page_id, limit=200)
        db.session.commit()
    return jsonify({"ok": True})


@facebook_routing_bp.post("/api/facebook-routing/employees/<int:employee_id>/cap")
def save_employee_cap(employee_id: int):
    employee, is_admin = _actor()
    if not can_manage_routing(employee, is_admin=is_admin):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ensure_facebook_routing_schema()
    data = request.get_json(silent=True) or {}
    try:
        cap = max(1, min(80, int(data.get("max_active") or 10)))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "الحد غير صالح"}), 400
    target = Employee.query.get(employee_id)
    if not target or not target.is_active:
        return jsonify({"ok": False, "error": "الموظف غير موجود"}), 404
    state = _state(employee_id)
    state.max_active_conversations = cap
    page_id = str(data.get("page_id") or "").strip()
    if page_id:
        link = FacebookPageEmployee.query.filter_by(page_id=page_id, employee_id=employee_id).first()
        if link:
            link.max_active_conversations = cap
    db.session.commit()
    drain_unassigned_queue(page_id or None, limit=200)
    db.session.commit()
    from modules.facebook_routing.engine import capacity_payload

    return jsonify({"ok": True, "employee": {"id": employee_id, **capacity_payload(employee_id)}})


@facebook_routing_bp.post("/api/facebook-routing/me")
def save_me():
    employee, is_admin = _actor()
    if not employee:
        return jsonify({"ok": False, "error": "auth"}), 401
    if not can_use_inbox(employee) and not is_admin:
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ensure_facebook_routing_schema()
    data = request.get_json(silent=True) or {}
    state = _state(employee.id)
    if "accept_messages" in data:
        state.accept_messages = bool(data.get("accept_messages"))
    if data.get("presence") in {"AVAILABLE", "BUSY", "OFFLINE"}:
        state.presence = data["presence"]
    db.session.commit()
    if state.accept_messages and state.presence != "OFFLINE":
        drain_unassigned_queue()
        db.session.commit()
    return jsonify({
        "ok": True,
        "accept_messages": bool(state.accept_messages),
        "presence": state.presence,
    })


def _live_kind(state, now):
    seen = getattr(state, "last_seen_at", None)
    if not seen:
        return "offline", ""
    age = (now - seen).total_seconds()
    activity = (getattr(state, "activity", None) or "").lower()
    label = (getattr(state, "activity_label", None) or "") if activity in {"typing", "replying"} else ""
    if activity == "typing" and age <= 8:
        return "typing", label
    if activity == "replying" and age <= 20:
        return "replying", label
    if age <= 45:
        return "open", ""
    return "offline", ""


@facebook_routing_bp.post("/api/facebook-routing/pulse")
def pulse():
    employee, _is_admin = _actor()
    if not employee:
        return jsonify({"ok": True, "skipped": True})
    ensure_facebook_routing_schema()
    data = request.get_json(silent=True) or {}
    activity = str(data.get("activity") or "open")
    if activity not in {"open", "typing", "replying"}:
        activity = "open"
    state = _state(employee.id)
    state.last_seen_at = datetime.utcnow()
    state.activity = activity
    state.activity_label = str(data.get("label") or "").strip()[:80]
    db.session.commit()
    return jsonify({"ok": True})


@facebook_routing_bp.get("/api/facebook-routing/live")
def live():
    employee, is_admin = _actor()
    if not employee and not is_admin:
        return jsonify({"ok": False, "error": "auth"}), 401
    ensure_facebook_routing_schema()
    from modules.facebook_monitor.formatters import format_ago

    now = datetime.utcnow()
    people = []
    for state in FacebookEmployeeRouting.query.all():
        kind, label = _live_kind(state, now)
        if not getattr(state, "last_seen_at", None) and kind == "offline":
            continue
        people.append({
            "id": state.employee_id,
            "live": kind,
            "label": label,
            "seen_label": format_ago(state.last_seen_at, now) if kind == "offline" else "",
        })
    return jsonify({"ok": True, "people": people})


@facebook_routing_bp.get("/api/facebook-routing/me")
def get_me():
    employee, is_admin = _actor()
    if not employee:
        return jsonify({"ok": True, "accept_messages": True, "presence": "AVAILABLE"})
    ensure_facebook_routing_schema()
    state = _state(employee.id)
    return jsonify({
        "ok": True,
        "accept_messages": bool(state.accept_messages),
        "presence": state.presence,
        "active": _active_count(employee.id),
        "can_transfer": can_transfer(employee, is_admin=is_admin),
    })


@facebook_routing_bp.get("/api/facebook-routing/teammates")
def teammates():
    employee, is_admin = _actor()
    if not employee and not is_admin:
        return jsonify({"ok": False, "error": "auth"}), 401
    page_id = str(request.args.get("page_id") or "").strip()
    ensure_facebook_routing_schema()
    links = FacebookPageEmployee.query.filter_by(page_id=page_id, is_enabled=True).all() if page_id else []
    rows = []
    for link in links:
        emp = Employee.query.get(link.employee_id)
        if not emp or not emp.is_active or not can_use_inbox(emp):
            continue
        rows.append({"id": emp.id, "name": emp.name, "active": _active_count(emp.id)})
    if not rows:
        rows = [
            {"id": row.id, "name": row.name, "active": _active_count(row.id)}
            for row in Employee.query.filter_by(is_active=True).order_by(Employee.name.asc()).all()
            if can_use_inbox(row)
        ]
    rows.sort(key=lambda row: ((row.get("name") or "").lower(), row.get("active") or 0))
    return jsonify({"ok": True, "employees": rows})


@facebook_routing_bp.post("/api/facebook-routing/transfer")
def transfer():
    employee, is_admin = _actor()
    if not employee and not is_admin:
        return jsonify({"ok": False, "error": "auth"}), 401
    data = request.get_json(silent=True) or {}
    page_id = str(data.get("page_id") or "").strip()
    psid = str(data.get("customer_psid") or "").strip()
    new_id = int(data.get("employee_id") or 0)
    conversation = conversation_for_psid(page_id, psid)
    if not conversation:
        return jsonify({"ok": False, "error": "المحادثة غير موجودة"}), 404
    owns = can_transfer(employee, is_admin=is_admin) or (
        employee and int(conversation.assigned_employee_id or 0) == int(employee.id)
    )
    if not owns:
        return jsonify({"ok": False, "error": "غير مصرح بالتحويل"}), 403
    if new_id <= 0:
        return jsonify({"ok": False, "error": "اختر موظفاً"}), 400
    try:
        transfer_conversation(conversation, new_id, performed_by=(employee.id if employee else None), reason="manual")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})
