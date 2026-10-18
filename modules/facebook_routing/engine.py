"""Assign Facebook conversations to one employee, once, until transfer or close."""
from __future__ import annotations

from datetime import datetime, timedelta

from extensions import db
from models.employee import Employee
from modules.ai_sales.models import AISalesConversation
from modules.facebook_routing.models import (
    FacebookEmployeeRouting,
    FacebookPageEmployee,
    FacebookPageRouting,
    FacebookRoutingEvent,
)
from modules.facebook_routing.schema import ensure_facebook_routing_schema
from utils.permission_checks import employee_can

FACEBOOK_CHANNELS = {"messenger", "facebook", "instagram"}
CLOSED = {"closed"}
DEFAULT_MAX = 80


def routing_day_start(now: datetime | None = None) -> datetime:
    """UTC timestamp for midnight of the current Iraq business day."""
    local_now = (now or datetime.utcnow()) + timedelta(hours=3)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)


def is_facebook_channel(channel) -> bool:
    return str(getattr(channel, "channel_type", "") or "").lower() in FACEBOOK_CHANNELS


def page_key(channel) -> str:
    return str(getattr(channel, "page_id", "") or getattr(channel, "external_account_id", "") or "").strip()


def can_view_all(employee: Employee | None = None, *, is_admin: bool = False) -> bool:
    if is_admin:
        return True
    if not employee:
        return False
    if employee.role == "admin":
        return True
    return employee_can(employee, "facebook_employee_inbox.view_all") or employee_can(employee, "view_reports")


def can_use_inbox(employee: Employee | None) -> bool:
    if not employee:
        return False
    return (
        employee.role == "admin"
        or employee_can(employee, "view_messages")
        or employee_can(employee, "use_employee_desk")
    )


def can_manage_routing(employee: Employee | None, *, is_admin: bool = False) -> bool:
    if is_admin:
        return True
    if not employee:
        return False
    return employee.role == "admin" or employee_can(employee, "manage_settings") or employee_can(employee, "manage_pages") or employee_can(employee, "view_reports")


def can_transfer(employee: Employee | None, *, is_admin: bool = False) -> bool:
    if is_admin:
        return True
    if not employee:
        return False
    return employee.role == "admin" or can_use_inbox(employee) or employee_can(employee, "manage_employees")


def _log(*, conversation_id, page_id, old_id, new_id, action, reason="", performed_by=None):
    db.session.add(FacebookRoutingEvent(
        conversation_id=conversation_id,
        page_id=page_id or "",
        old_employee_id=old_id,
        new_employee_id=new_id,
        action=action,
        reason=(reason or "")[:300],
        performed_by=performed_by,
    ))


def _state(employee_id: int) -> FacebookEmployeeRouting:
    row = FacebookEmployeeRouting.query.filter_by(employee_id=employee_id).first()
    if row:
        return row
    row = FacebookEmployeeRouting(employee_id=employee_id, accept_messages=True, presence="AVAILABLE")
    db.session.add(row)
    db.session.flush()
    return row


def _waiting_filter(query):
    return query.filter(
        db.or_(
            db.and_(
                AISalesConversation.last_customer_message_at.isnot(None),
                db.or_(
                    AISalesConversation.last_business_message_at.is_(None),
                    AISalesConversation.last_customer_message_at > AISalesConversation.last_business_message_at,
                ),
            ),
            db.and_(
                AISalesConversation.last_customer_message_at.is_(None),
                AISalesConversation.last_business_message_at.is_(None),
            ),
        )
    )


def _active_count(employee_id: int, page_id: str | None = None) -> int:
    """Slots in use: assigned conversations still waiting for a reply."""
    query = AISalesConversation.query.filter(
        AISalesConversation.assigned_employee_id == employee_id,
        AISalesConversation.status.notin_(tuple(CLOSED)),
    )
    if page_id:
        from modules.ai_sales.models import AISalesChannelAccount

        channel_ids = [
            row.id
            for row in AISalesChannelAccount.query.filter(AISalesChannelAccount.page_id == page_id).all()
        ]
        if not channel_ids:
            return 0
        query = query.filter(AISalesConversation.channel_account_id.in_(channel_ids))
    return _waiting_filter(query).count()


def _employee_cap(employee_id: int, page_id: str | None = None) -> int:
    state = _state(employee_id)
    cap = max(1, int(state.max_active_conversations or 10))
    if not page_id:
        return min(DEFAULT_MAX, cap)
    link = FacebookPageEmployee.query.filter_by(page_id=page_id, employee_id=employee_id).first()
    if link and link.max_active_conversations:
        return max(1, min(DEFAULT_MAX, int(link.max_active_conversations)))
    routing = _page_routing(page_id)
    if routing and routing.default_max_conversations:
        return max(1, min(cap, int(routing.default_max_conversations)))
    return min(DEFAULT_MAX, cap)


def capacity_payload(employee_id: int) -> dict:
    cap = _employee_cap(employee_id)
    load = _active_count(employee_id)
    queue = 0
    try:
        from modules.ai_sales.models import AISalesChannelAccount

        page_ids = [
            str(row.page_id)
            for row in FacebookPageEmployee.query.filter_by(employee_id=employee_id, is_enabled=True).all()
            if row.page_id
        ]
        if page_ids:
            channel_ids = [
                row.id for row in AISalesChannelAccount.query.filter(
                    AISalesChannelAccount.page_id.in_(page_ids)
                ).all()
            ]
            if channel_ids:
                queue = AISalesConversation.query.filter(
                    AISalesConversation.channel_account_id.in_(channel_ids),
                    AISalesConversation.assigned_employee_id.is_(None),
                    AISalesConversation.status.notin_(tuple(CLOSED)),
                ).count()
    except Exception:
        queue = 0
    return {
        "cap": cap,
        "load": load,
        "free": max(0, cap - load),
        "full": load >= cap,
        "queue": queue,
    }


def _page_routing(page_id: str) -> FacebookPageRouting | None:
    if not page_id:
        return None
    return FacebookPageRouting.query.filter_by(page_id=page_id).first()


def _employee_still_valid(employee_id: int, page_id: str, routing: FacebookPageRouting | None) -> bool:
    employee = Employee.query.get(employee_id)
    if not employee or not employee.is_active:
        return False
    if routing and routing.routing_enabled:
        link = FacebookPageEmployee.query.filter_by(page_id=page_id, employee_id=employee_id, is_enabled=True).first()
        if not link:
            return False
    return True


def reply_timeout_seconds(employee_id: int, page_id: str | None = None) -> int:
    state = _state(employee_id)
    custom = getattr(state, "reply_timeout_seconds", None)
    if custom:
        return max(60, min(3600, int(custom)))
    routing = _page_routing(page_id or "")
    page_timeout = getattr(routing, "reply_timeout_seconds", None) if routing else None
    if page_timeout:
        return max(60, min(3600, int(page_timeout)))
    return 180


def eligible_employees(
    page_id: str,
    routing: FacebookPageRouting,
    exclude_ids: set[int] | None = None,
    *,
    allow_single_overflow: bool = False,
) -> list[tuple[Employee, FacebookPageEmployee, FacebookEmployeeRouting, int]]:
    links = FacebookPageEmployee.query.filter_by(page_id=page_id, is_enabled=True).all()
    available = []
    pool = []
    for link in links:
        employee = Employee.query.get(link.employee_id)
        if not employee or not employee.is_active:
            continue
        if exclude_ids and int(employee.id) in exclude_ids:
            continue
        if not can_use_inbox(employee):
            continue
        state = _state(employee.id)
        if not state.accept_messages:
            continue
        if (state.presence or "AVAILABLE").upper() == "OFFLINE":
            continue
        cap = _employee_cap(employee.id, page_id)
        active = _active_count(employee.id, page_id)
        available.append((employee, link, state, active))
        if _active_count(employee.id) >= _employee_cap(employee.id):
            continue
        if active >= cap:
            continue
        pool.append((employee, link, state, active))
    # A page routed to exactly one available employee must not silently hide
    # fresh messages merely because imported/older threads filled the nominal
    # concurrency cap.  The cap still controls queue draining and balancing
    # when more than one employee is available.
    if not pool and allow_single_overflow and len(available) == 1:
        pool = available
    pool.sort(key=lambda row: (row[3], row[1].last_assigned_at or datetime(2000, 1, 1)))
    return pool


def _assign(conversation: AISalesConversation, employee_id: int, *, page_id: str, method: str, reason: str, performed_by=None):
    old = conversation.assigned_employee_id
    conversation.assigned_employee_id = employee_id
    if hasattr(conversation, "assigned_at"):
        conversation.assigned_at = datetime.utcnow()
    if hasattr(conversation, "assignment_method"):
        conversation.assignment_method = method
    if conversation.status in CLOSED or conversation.status == "open":
        conversation.status = "waiting_employee"
    conversation.human_takeover = True
    link = FacebookPageEmployee.query.filter_by(page_id=page_id, employee_id=employee_id).first()
    if link:
        link.last_assigned_at = datetime.utcnow()
    _log(
        conversation_id=conversation.id,
        page_id=page_id,
        old_id=old,
        new_id=employee_id,
        action="CONVERSATION_ASSIGNED" if not old else "CONVERSATION_TRANSFERRED",
        reason=reason,
        performed_by=performed_by,
    )


def apply_inbound_routing(
    conversation: AISalesConversation,
    channel,
    *,
    allow_single_overflow: bool = True,
) -> None:
    """Call after get_or_create_conversation. Never raises to the webhook."""
    if not conversation or not is_facebook_channel(channel):
        return
    try:
        ensure_facebook_routing_schema()
    except Exception:
        db.session.rollback()
        return
    page_id = page_key(channel)
    routing = _page_routing(page_id)
    current = conversation.assigned_employee_id

    if current and _employee_still_valid(current, page_id, routing):
        return

    if not routing or not routing.routing_enabled:
        if current and not _employee_still_valid(current, page_id, routing):
            conversation.assigned_employee_id = None
            _log(
                conversation_id=conversation.id,
                page_id=page_id,
                old_id=current,
                new_id=None,
                action="ROUTING_PAGE_DISABLED",
                reason="page routing off or assignee invalid",
            )
        elif not current:
            _log(
                conversation_id=conversation.id,
                page_id=page_id,
                old_id=None,
                new_id=None,
                action="ROUTING_PAGE_DISABLED",
                reason="monitor only",
            )
        return

    if current and not _employee_still_valid(current, page_id, routing):
        conversation.assigned_employee_id = None
        current = None

    if conversation.assigned_employee_id:
        return

    pool = eligible_employees(
        page_id,
        routing,
        allow_single_overflow=allow_single_overflow,
    )
    if not pool:
        _log(
            conversation_id=conversation.id,
            page_id=page_id,
            old_id=None,
            new_id=None,
            action="ROUTING_FAILED_NO_AGENT",
            reason="no eligible employee",
        )
        return
    employee, _link, _state_row, _active = pool[0]
    _assign(conversation, employee.id, page_id=page_id, method="LEAST_ACTIVE", reason="inbound")


def attach_assignments(events: list[dict], *, assign_missing: bool = True) -> None:
    """Stamp Graph/monitor rows with the assigned employee, and create+route missing threads."""
    if not events:
        return
    try:
        reassign_overdue()
    except Exception:
        db.session.rollback()
    try:
        ensure_facebook_routing_schema()
    except Exception:
        db.session.rollback()
        return
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount

    dirty = False
    channels: dict[str, object] = {}
    for event in events:
        page_id = str(event.get("external_page_id") or "").strip()
        psid = str(event.get("customer_psid") or "").strip()
        if not page_id or not psid:
            continue
        conversation = conversation_for_psid(page_id, psid)
        routing = _page_routing(page_id)
        if not conversation and assign_missing and routing and routing.routing_enabled:
            if page_id not in channels:
                channels[page_id] = AISalesChannelAccount.query.filter(
                    AISalesChannelAccount.page_id == page_id,
                    AISalesChannelAccount.channel_type.in_(tuple(FACEBOOK_CHANNELS)),
                ).first()
            channel = channels[page_id]
            if channel:
                conversation = get_or_create_conversation(
                    channel,
                    external_contact_id=psid,
                    phone="",
                    contact_name=event.get("customer_name") or "",
                )
                preview = str(event.get("preview") or "").strip()
                if preview:
                    conversation.summary = preview[:300]
                unread = int(event.get("unread_count") or 0)
                received = str(event.get("received_at") or "").strip()
                stamp = None
                if received:
                    try:
                        stamp = datetime.fromisoformat(received.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        stamp = None
                if stamp:
                    conversation.updated_at = stamp
                    if unread or not conversation.last_customer_message_at:
                        conversation.last_customer_message_at = stamp
                dirty = True
        if conversation and assign_missing and not conversation.assigned_employee_id and routing and routing.routing_enabled:
            apply_inbound_routing(conversation, conversation.channel)
            dirty = True
        if not conversation:
            continue
        assigned = conversation.assigned_employee_id
        event["assigned_employee_id"] = assigned
        event["assignment_status"] = "ASSIGNED" if assigned else "UNASSIGNED"
        event["ai_conversation_id"] = conversation.id
        if assigned:
            event["employee_id"] = assigned
            name = ""
            if getattr(conversation, "assigned_employee", None):
                name = conversation.assigned_employee.name or ""
            event["employee_name"] = name or event.get("employee_name") or ""
    if dirty:
        db.session.commit()


def reassign_overdue(limit: int = 30) -> int:
    """Move unanswered threads to the next available employee after the reply timer."""
    try:
        ensure_facebook_routing_schema()
    except Exception:
        db.session.rollback()
        return 0
    now = datetime.utcnow()
    waiting = _waiting_filter(
        AISalesConversation.query.filter(
            AISalesConversation.assigned_employee_id.isnot(None),
            AISalesConversation.status.notin_(tuple(CLOSED)),
            AISalesConversation.last_customer_message_at.isnot(None),
        )
    ).limit(200).all()
    moved = 0
    for conversation in waiting:
        if moved >= limit:
            break
        channel = conversation.channel
        if not channel or not is_facebook_channel(channel):
            continue
        page_id = page_key(channel)
        routing = _page_routing(page_id)
        if not routing or not routing.routing_enabled:
            continue
        started = conversation.last_customer_message_at
        assigned_at = getattr(conversation, "assigned_at", None)
        if assigned_at and started and assigned_at > started:
            started = assigned_at
        if not started:
            continue
        timeout = reply_timeout_seconds(int(conversation.assigned_employee_id), page_id)
        if (now - started).total_seconds() < timeout:
            continue
        pool = eligible_employees(page_id, routing, exclude_ids={int(conversation.assigned_employee_id)})
        if not pool:
            continue
        _assign(
            conversation,
            pool[0][0].id,
            page_id=page_id,
            method="TIMEOUT",
            reason="reply timeout",
        )
        moved += 1
    if moved:
        db.session.commit()
    return moved


def refill_after_reply(page_id: str | None = None, limit: int = 3) -> int:
    """A reply frees one waiting slot; pull the next queued thread into it."""
    try:
        ensure_facebook_routing_schema()
        taken = drain_unassigned_queue(page_id, limit=limit)
        if page_id and taken < 1:
            taken += drain_unassigned_queue(None, limit=limit)
        if taken:
            db.session.commit()
        return taken
    except Exception:
        db.session.rollback()
        return 0


def drain_unassigned_queue(
    page_id: str | None = None,
    limit: int = 20,
    *,
    since: datetime | None = None,
    ignore_capacity: bool = False,
) -> int:
    ensure_facebook_routing_schema()
    since = since or routing_day_start()
    query = AISalesConversation.query.filter(
        AISalesConversation.assigned_employee_id.is_(None),
        AISalesConversation.status.notin_(tuple(CLOSED)),
        AISalesConversation.last_customer_message_at.isnot(None),
        AISalesConversation.last_customer_message_at >= since,
    )
    if page_id:
        from modules.ai_sales.models import AISalesChannelAccount

        channel_ids = [
            row.id for row in AISalesChannelAccount.query.filter(
                AISalesChannelAccount.page_id == page_id
            ).all()
        ]
        if not channel_ids:
            return 0
        query = query.filter(AISalesConversation.channel_account_id.in_(channel_ids))
    # Configuration changes should fill the employee desk with the newest
    # customer activity, not historical imports from days or months ago.
    rows = query.order_by(
        AISalesConversation.last_customer_message_at.desc(),
        AISalesConversation.updated_at.desc(),
    ).limit(limit).all()
    assigned = 0
    for conversation in rows:
        channel = conversation.channel
        if not channel:
            continue
        before = conversation.assigned_employee_id
        if ignore_capacity:
            if _force_assign_least_loaded(conversation, channel):
                assigned += 1
            continue
        apply_inbound_routing(conversation, channel, allow_single_overflow=False)
        if conversation.assigned_employee_id and conversation.assigned_employee_id != before:
            assigned += 1
    return assigned


def _force_assign_least_loaded(conversation: AISalesConversation, channel) -> bool:
    """Assign past backlog even when every employee is already at nominal capacity."""
    if not conversation or not is_facebook_channel(channel):
        return False
    page_id = page_key(channel)
    routing = _page_routing(page_id)
    if not routing or not routing.routing_enabled:
        return False
    links = FacebookPageEmployee.query.filter_by(page_id=page_id, is_enabled=True).all()
    pool = []
    for link in links:
        employee = Employee.query.get(link.employee_id)
        if not employee or not employee.is_active:
            continue
        if not can_use_inbox(employee):
            continue
        state = _state(employee.id)
        if not state.accept_messages:
            continue
        if (state.presence or "AVAILABLE").upper() == "OFFLINE":
            continue
        pool.append((employee, link, _active_count(employee.id), link.last_assigned_at or datetime(2000, 1, 1)))
    if not pool:
        return False
    pool.sort(key=lambda row: (row[2], row[3]))
    employee = pool[0][0]
    before = conversation.assigned_employee_id
    _assign(
        conversation,
        employee.id,
        page_id=page_id,
        method="BACKLOG",
        reason="recover past days",
    )
    return bool(conversation.assigned_employee_id and conversation.assigned_employee_id != before)


def transfer_conversation(conversation: AISalesConversation, new_employee_id: int, *, performed_by=None, reason="manual") -> None:
    channel = conversation.channel
    page_id = page_key(channel) if channel else ""
    if not Employee.query.get(new_employee_id):
        raise ValueError("الموظف غير موجود")
    _assign(
        conversation,
        new_employee_id,
        page_id=page_id,
        method="MANUAL",
        reason=reason,
        performed_by=performed_by,
    )


def conversation_for_psid(page_id: str, psid: str) -> AISalesConversation | None:
    from modules.ai_sales.models import AISalesChannelAccount

    if not page_id or not psid:
        return None
    channels = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.page_id == str(page_id),
        AISalesChannelAccount.channel_type.in_(tuple(FACEBOOK_CHANNELS)),
    ).all()
    ids = [row.id for row in channels]
    if not ids:
        return None
    return (
        AISalesConversation.query.filter(
            AISalesConversation.channel_account_id.in_(ids),
            AISalesConversation.external_contact_id == str(psid),
        )
        .order_by(AISalesConversation.updated_at.desc())
        .first()
    )


def assert_employee_owns(conversation: AISalesConversation | None, employee: Employee | None, *, is_admin: bool = False) -> bool:
    if can_view_all(employee, is_admin=is_admin):
        return True
    if not conversation or not employee:
        return False
    return int(conversation.assigned_employee_id or 0) == int(employee.id)
