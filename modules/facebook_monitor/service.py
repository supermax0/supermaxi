"""Aggregate Facebook monitoring data from existing Finora tables."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from models.employee import Employee
from models.invoice import Invoice
from modules.ai_sales.models import (
    AISalesChannelAccount,
    AISalesConversation,
    AISalesMessage,
)
from modules.facebook_monitor.formatters import (
    format_ago,
    format_duration,
    format_iqd,
    format_percent,
    format_relative,
    format_usd,
    parse_date_range,
)
from modules.facebook_monitor.status import STATUS_LABELS, classify_message, response_tone
from modules.facebook_monitor.strength import page_strength_score, score_tone
from modules.publisher.models.publisher_page import PublisherPage
from utils.meta_graph import GRAPH_BASE
from utils.order_status import CANCELED_STATUSES, COMPLETED_STATUSES, PENDING_STATUSES, RETURN_STATUSES

ONLINE_WINDOW = timedelta(minutes=10)
PAGE_SIZE = 40
CHANNEL_TYPES = ("messenger", "facebook")
MESSAGE_CAP = 300
_GRAPH_CACHE = {}
_GRAPH_CACHE_TTL = 900
_GRAPH_COOLDOWN_SEC = 70 * 60
_GRAPH_COOLDOWN_UNTIL = 0.0
_ADS_CACHE = {}
_ADS_CACHE_TTL = 1800
_LIMIT_HINT = "فيسبوك أوقف الطلبات مؤقتاً. نعرض البيانات المحفوظة، والرسائل الجديدة توصل من الويب هوك."


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _capacity_for(employee_id: int) -> dict:
    try:
        from modules.facebook_routing.engine import capacity_payload

        return capacity_payload(employee_id)
    except Exception:
        return {"cap": 10, "load": 0, "free": 10, "full": False, "queue": 0}


def _preview_line(text: str, *, outbound: bool) -> str:
    clean = str(text or "").strip()
    for prefix in ("أنت: ", "انت: ", "العميل: "):
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
            break
    if not clean:
        clean = "رسالة بدون نص"
    return f"أنت: {clean}" if outbound else f"العميل: {clean}"


def _initials(name: str | None) -> str:
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "ف"
    if len(parts) == 1:
        return parts[0][:2]
    return parts[0][:1] + parts[1][:1]


def _int_or_none(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _bool_or_none(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def _loads_order_id(conversation):
    if not conversation:
        return None
    raw = conversation.get_context().get("created_order_id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _ad_context(conversation, message=None) -> dict:
    meta = message.get_media_metadata() if message is not None else {}
    ad = dict((meta or {}).get("ad_context") or {})
    if not ad and conversation is not None:
        ad = dict(conversation.get_context().get("ad_context") or {})
    return ad


def build_snapshot(args: dict, *, now: datetime | None = None, tenant_id: int | None = None, tenant_slug: str | None = None, include_raw: bool = False, skip_graph: bool = True) -> dict:
    now = now or datetime.utcnow()
    preset, start, end = parse_date_range(
        args.get("range") or args.get("preset"), args.get("from"), args.get("to"), now
    )
    page_key = str(args.get("page_id") or "").strip()
    employee_id = _int_or_none(args.get("employee_id"))
    ad_id = str(args.get("ad_id") or "").strip()
    status = str(args.get("status") or "").strip().upper()
    search = str(args.get("search") or args.get("q") or "").strip()
    has_order = _bool_or_none(args.get("has_order"))
    sort = str(args.get("employee_sort") or "default")
    cursor = str(args.get("cursor") or "").strip()
    try:
        limit = min(50, max(1, int(args.get("limit") or PAGE_SIZE)))
    except (TypeError, ValueError):
        limit = PAGE_SIZE

    channels = (
        AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CHANNEL_TYPES))
        .order_by(AISalesChannelAccount.name.asc())
        .all()
    )
    cache_key = f"{tenant_slug or ''}|{page_key}|{start.date()}|{end.date()}"
    cached = _graph_cache_get(cache_key)
    if cached:
        pages, graph_events, graph_error = cached
    else:
        pages, graph_error = _load_pages(channels, tenant_slug)
        if skip_graph or _graph_cooling():
            graph_events = []
            if _graph_cooling() and not graph_error:
                graph_error = _LIMIT_HINT
        else:
            _apply_page_tokens(pages, tenant_slug)
            selected_now = next((page for page in pages if page["id"] == page_key), None)
            graph_events, message_error = _graph_message_events(selected_now and [selected_now] or pages, start, end, now)
            if message_error and not graph_error:
                graph_error = message_error
        _graph_cache_set(cache_key, pages, graph_events, graph_error)
    invoices = _range_invoices(start, end, tenant_id)
    invoice_by_id = {row.id: row for row in invoices}

    channel_ids = [page["channel_id"] for page in pages if page["channel_id"]]
    inbound = _load_inbound(channel_ids, start, end)
    # Keep open/late threads visible even when they fall outside the selected day filter.
    open_inbound = _load_open_inbound(channel_ids, start, {row.id for row in inbound})
    if open_inbound:
        known_inbound = {row.id for row in inbound}
        inbound.extend(row for row in open_inbound if row.id not in known_inbound)
    conversations = _load_conversations(inbound)
    outbound_map = _first_outbound_after(inbound)
    events = [
        _message_event(
            message,
            conversations.get(message.conversation_id),
            outbound_map.get(message.id),
            invoice_by_id,
            pages,
            now,
        )
        for message in inbound
    ]
    selected = next((page for page in pages if page["id"] == page_key), None)
    known = {str(event["id"]) for event in events}
    events.extend(event for event in graph_events if str(event["id"]) not in known)
    try:
        from modules.facebook_routing.engine import attach_assignments

        # Opening the monitor is read-only.  Historical Graph/import rows must
        # never consume employee capacity; live webhook events are routed when
        # they are ingested by AI Sales.
        attach_assignments(events, assign_missing=False)
    except Exception:
        from extensions import db

        db.session.rollback()
    try:
        apply_local_replies(events, now)
        apply_unread_counts(events)
    except Exception:
        from extensions import db

        db.session.rollback()
    for page in pages:
        page.pop("_token", None)
    ranked_events = list(events)
    ranked_invoices = list(invoices)

    marketing_ads, ads_error = _graph_active_ads(tenant_slug, start, end, allow_fetch=not skip_graph)
    _link_events_to_ads(ranked_events, marketing_ads)
    _attribute_orders_to_ad_events(ranked_events, ranked_invoices)
    if ads_error and not graph_error:
        graph_error = ads_error

    if selected:
        events = [event for event in events if event["page_id"] == selected["id"]]
        invoices = [row for row in invoices if _page_match(row, selected) or row.id in {event["order_id"] for event in events if event["order_id"]}]
    if employee_id:
        events = [event for event in events if event["employee_id"] == employee_id]
        invoices = [row for row in invoices if row.employee_id == employee_id]
    if search:
        needle = search.lower()
        events = [event for event in events if needle in event["search_text"]]
    ad_source = list(events)
    if ad_id:
        events = [event for event in events if event["ad_id"] == ad_id]
        linked = {event["order_id"] for event in events if event["order_id"]}
        invoices = [row for row in invoices if row.id in linked]

    status_counts = _status_counts(events)
    visible = list(events)
    if status and status != "ALL":
        visible = [event for event in visible if event["status"] == status]
    if has_order is True:
        visible = [event for event in visible if event["order_id"]]
    elif has_order is False:
        visible = [event for event in visible if not event["order_id"]]

    visible.sort(key=lambda event: event["received_at"] or "", reverse=True)
    paged, next_cursor = _cursor_page(visible, cursor, limit)

    employees = _load_employees(tenant_id)
    page_rows = _rank_pages(pages, ranked_events, ranked_invoices)
    employee_rows = _employee_rows(employees, invoices, events, now, sort, selected)
    ad_rows = _ad_rows(ad_source, marketing_ads)
    # Keep soft messaging permission hints.

    sales = sum(int(row.total or 0) for row in invoices if _norm(row.status) not in CANCELED_STATUSES)
    returns = sum(1 for row in invoices if _norm(row.status) in RETURN_STATUSES)
    payload = {
        "range": preset,
        "from": start.date().isoformat(),
        "to": (end - timedelta(days=1)).date().isoformat(),
        "filters": {
            "page_id": page_key,
            "employee_id": employee_id,
            "ad_id": ad_id,
            "status": status,
            "search": search,
            "has_order": has_order,
            "employee_sort": sort,
        },
        "overview": {
            "pages": len(pages),
            "messages": status_counts["ALL"],
            "orders": len({row.id for row in invoices}),
            "returns": returns,
            "sales": sales,
            "sales_label": format_iqd(sales, compact=True),
            "active_employees": sum(1 for row in employee_rows if row["presence"] == "online"),
            "offline_employees": sum(1 for row in employee_rows if row["presence"] == "offline"),
            "active_ads": len(ad_rows),
            "last_updated_at": now.isoformat(),
        },
        "status_counts": status_counts,
        "pages": page_rows,
        "messages": paged,
        "next_cursor": next_cursor,
        "employees": employee_rows,
        "ads": ad_rows,
        "meta": _meta_banner(channels, now, graph_error),
        "facebook_pull": facebook_pull_status(),
        "filter_options": {
            "pages": [{"id": page["id"], "name": page["name"]} for page in pages],
            "employees": [{"id": row.id, "name": row.name} for row in employees],
            "ads": [{"id": row["id"], "name": row["name"]} for row in ad_rows],
            "statuses": [{"id": key, "label": label} for key, label in STATUS_LABELS.items()],
        },
    }
    if include_raw:
        payload["_events"] = events
        payload["_invoices"] = invoices
    return payload


def employee_detail(employee_id: int, args: dict, *, now: datetime | None = None, tenant_id: int | None = None) -> dict | None:
    now = now or datetime.utcnow()
    employee = Employee.query.get(employee_id)
    if not employee:
        return None
    preset, start, end = parse_date_range(args.get("range"), args.get("from"), args.get("to"), now)
    invoices = Invoice.query.filter(
        Invoice.deleted_at.is_(None),
        Invoice.employee_id == employee_id,
        Invoice.created_at >= start,
        Invoice.created_at < end,
    ).all()
    snapshot = build_snapshot(
        {**args, "employee_id": employee_id, "status": "", "limit": 50},
        now=now,
        tenant_id=tenant_id,
        tenant_slug=args.get("tenant_slug"),
        skip_graph=True,
    )
    row = next((item for item in snapshot["employees"] if item["id"] == employee_id), None)
    speeds = []
    handled = snapshot["status_counts"]["ALL"]
    # Pull response times from the unpaged filtered set via a second narrow pass.
    detail_args = {**args, "employee_id": employee_id, "status": "", "limit": 50}
    detail_args.pop("cursor", None)
    full_events = _events_for(detail_args, now=now, tenant_id=tenant_id)
    speeds = [
        event["response_seconds"]
        for event in full_events
        if event["response_seconds"] is not None and event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"}
    ]
    handled = len(full_events)
    page_key = str(args.get("page_id") or "")
    if page_key:
        selected = next((page for page in snapshot["pages"] if page["id"] == page_key), None)
        if selected:
            invoices = [invoice for invoice in invoices if _page_match(invoice, selected)]
    pages_breakdown: dict[str, dict] = {}
    for invoice in invoices:
        name = invoice.page_name or "بدون صفحة"
        bucket = pages_breakdown.setdefault(name, {"orders": 0, "sales": 0})
        bucket["orders"] += 1
        if _norm(invoice.status) not in CANCELED_STATUSES:
            bucket["sales"] += int(invoice.total or 0)
    sales = sum(int(invoice.total or 0) for invoice in invoices if _norm(invoice.status) not in CANCELED_STATUSES)
    completed = sum(1 for invoice in invoices if _norm(invoice.status) in COMPLETED_STATUSES)
    returns = sum(1 for invoice in invoices if _norm(invoice.status) in RETURN_STATUSES)
    cancelled = sum(1 for invoice in invoices if _norm(invoice.status) in CANCELED_STATUSES)
    pending = sum(1 for invoice in invoices if _norm(invoice.status) in PENDING_STATUSES)
    live = [invoice for invoice in invoices if _norm(invoice.status) not in CANCELED_STATUSES]
    waiting = sum(1 for event in full_events if event["status"] in {"NEW", "WAITING_REPLY"})
    late = sum(1 for event in full_events if event["status"] == "LATE")
    answered = sum(1 for event in full_events if event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"})
    last_order = max((invoice.created_at for invoice in invoices if invoice.created_at), default=None)
    last_message = max((event.get("received_at") for event in full_events if event.get("received_at")), default=None)
    last_message_at = None
    if last_message:
        try:
            last_message_at = datetime.fromisoformat(str(last_message).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            last_message_at = None
    open_chats = 0
    waiting_chats = 0
    try:
        from modules.ai_sales.models import AISalesConversation

        convos = AISalesConversation.query.filter(
            AISalesConversation.assigned_employee_id == employee_id,
            AISalesConversation.status != "closed",
        ).all()
        open_chats = len(convos)
        for convo in convos:
            last_c = convo.last_customer_message_at
            last_b = convo.last_business_message_at
            if last_c and (not last_b or last_c > last_b):
                waiting_chats += 1
    except Exception:
        from extensions import db

        db.session.rollback()
    range_labels = {
        "today": "اليوم",
        "yesterday": "أمس",
        "last_7": "آخر 7 أيام",
        "last_30": "آخر 30 يوم",
        "this_month": "هذا الشهر",
        "all": "الكل",
        "custom": "فترة محددة",
    }
    return {
        "id": employee.id,
        "name": employee.name,
        "avatar": ("/" + employee.profile_pic) if employee.profile_pic else "",
        "initials": _initials(employee.name),
        "presence": (row or {}).get("presence") or "offline",
        "orders": len(invoices),
        "completed": completed,
        "pending": pending,
        "returns": returns,
        "cancelled": cancelled,
        "customers": len({invoice.customer_id or invoice.customer_name for invoice in invoices}),
        "conversion": format_percent((completed / len(invoices) * 100) if invoices else None),
        "return_rate": format_percent((returns / len(invoices) * 100) if invoices else None),
        "avg_ticket": int(sales / len(live)) if live else 0,
        "avg_ticket_label": format_iqd(int(sales / len(live)) if live else 0),
        "sales": sales,
        "sales_label": format_iqd(sales),
        "avg_response": format_duration(int(sum(speeds) / len(speeds)) if speeds else None),
        "fastest": format_duration(min(speeds) if speeds else None),
        "slowest": format_duration(max(speeds) if speeds else None),
        "handled_messages": handled,
        "waiting_messages": waiting,
        "late_messages": late,
        "answered_messages": answered,
        "reply_rate": format_percent((answered / handled * 100) if handled else None),
        "open_chats": open_chats,
        "waiting_chats": waiting_chats,
        "last_order_label": format_relative(last_order, now),
        "last_message_label": format_relative(last_message_at, now),
        "pages": [
            {"name": name, "orders": item["orders"], "sales": item["sales"], "sales_label": format_iqd(item["sales"])}
            for name, item in sorted(pages_breakdown.items(), key=lambda pair: pair[1]["sales"], reverse=True)
        ],
        "range": preset,
        "range_label": range_labels.get(preset, "اليوم"),
        **_capacity_for(employee.id),
    }


def page_detail(page_id: str, args: dict, *, now: datetime | None = None, tenant_id: int | None = None) -> dict | None:
    now = now or datetime.utcnow()
    page_key = str(page_id or "").strip()
    if not page_key:
        return None
    snapshot = build_snapshot(
        {**args, "page_id": "", "employee_id": "", "status": "", "limit": 1},
        now=now,
        tenant_id=tenant_id,
        tenant_slug=args.get("tenant_slug"),
        skip_graph=True,
    )
    ranked = next((row for row in snapshot["pages"] if str(row.get("id")) == page_key), None)
    if not ranked:
        return None
    preset, start, end = parse_date_range(args.get("range"), args.get("from"), args.get("to"), now)
    channels = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CHANNEL_TYPES)).all()
    pages, _err = _load_pages(channels, args.get("tenant_slug"))
    selected = next((page for page in pages if str(page.get("id")) == page_key), None)
    match_page = selected or {"name": ranked.get("name") or ""}
    invoices = [row for row in _range_invoices(start, end, tenant_id) if _page_match(row, match_page)]
    events = _events_for({**args, "page_id": page_key, "employee_id": ""}, now=now, tenant_id=tenant_id)
    speeds = [
        event["response_seconds"]
        for event in events
        if event["response_seconds"] is not None and event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"}
    ]
    completed = sum(1 for invoice in invoices if _norm(invoice.status) in COMPLETED_STATUSES)
    returns = sum(1 for invoice in invoices if _norm(invoice.status) in RETURN_STATUSES)
    cancelled = sum(1 for invoice in invoices if _norm(invoice.status) in CANCELED_STATUSES)
    pending = sum(1 for invoice in invoices if _norm(invoice.status) in PENDING_STATUSES)
    live = [invoice for invoice in invoices if _norm(invoice.status) not in CANCELED_STATUSES]
    sales = sum(int(invoice.total or 0) for invoice in live)
    waiting = sum(1 for event in events if event["status"] in {"NEW", "WAITING_REPLY"})
    late = sum(1 for event in events if event["status"] == "LATE")
    answered = sum(1 for event in events if event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"})
    last_order = max((invoice.created_at for invoice in invoices if invoice.created_at), default=None)
    last_message = max((event.get("received_at") for event in events if event.get("received_at")), default=None)
    last_message_at = None
    if last_message:
        try:
            last_message_at = datetime.fromisoformat(str(last_message).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            last_message_at = None
    ext = str((selected or {}).get("external_page_id") or "")
    routing_on = False
    queue = 0
    staff = []
    try:
        from modules.facebook_routing.engine import capacity_payload
        from modules.facebook_routing.models import FacebookPageEmployee, FacebookPageRouting

        routing = FacebookPageRouting.query.filter_by(page_id=ext).first() if ext else None
        routing_on = bool(routing and routing.routing_enabled)
        if selected and selected.get("channel_id"):
            queue = AISalesConversation.query.filter(
                AISalesConversation.channel_account_id == selected["channel_id"],
                AISalesConversation.assigned_employee_id.is_(None),
                AISalesConversation.status != "closed",
            ).count()
        seen = set()
        for link in FacebookPageEmployee.query.filter_by(page_id=ext, is_enabled=True).all() if ext else []:
            employee = Employee.query.get(link.employee_id)
            if not employee or not employee.is_active:
                continue
            seen.add(employee.id)
            cap = capacity_payload(employee.id)
            mine = [invoice for invoice in invoices if invoice.employee_id == employee.id]
            staff.append({
                "id": employee.id,
                "name": employee.name,
                "load": cap["load"],
                "cap": cap["cap"],
                "full": cap["full"],
                "orders": len(mine),
                "sales": sum(int(invoice.total or 0) for invoice in mine if _norm(invoice.status) not in CANCELED_STATUSES),
                "sales_label": format_iqd(sum(int(invoice.total or 0) for invoice in mine if _norm(invoice.status) not in CANCELED_STATUSES)),
            })
        for invoice in invoices:
            emp_id = invoice.employee_id
            if not emp_id or emp_id in seen:
                continue
            employee = Employee.query.get(emp_id)
            if not employee:
                continue
            seen.add(emp_id)
            mine = [row for row in invoices if row.employee_id == emp_id]
            staff.append({
                "id": employee.id,
                "name": employee.name,
                "load": 0,
                "cap": 0,
                "full": False,
                "orders": len(mine),
                "sales": sum(int(row.total or 0) for row in mine if _norm(row.status) not in CANCELED_STATUSES),
                "sales_label": format_iqd(sum(int(row.total or 0) for row in mine if _norm(row.status) not in CANCELED_STATUSES)),
            })
        staff.sort(key=lambda row: (row["sales"], row["orders"]), reverse=True)
    except Exception:
        from extensions import db

        db.session.rollback()
    range_labels = {
        "today": "اليوم",
        "yesterday": "أمس",
        "last_7": "آخر 7 أيام",
        "last_30": "آخر 30 يوم",
        "this_month": "هذا الشهر",
        "all": "الكل",
        "custom": "فترة محددة",
    }
    return {
        "id": ranked["id"],
        "name": ranked["name"],
        "avatar": ranked.get("avatar") or "",
        "initials": ranked.get("initials") or _initials(ranked["name"]),
        "external_page_id": ext,
        "score": ranked.get("score") or 0,
        "tone": ranked.get("tone") or "muted",
        "rank": ranked.get("rank") or 0,
        "routing_on": routing_on,
        "queue": queue,
        "orders": len(invoices),
        "completed": completed,
        "pending": pending,
        "returns": returns,
        "cancelled": cancelled,
        "customers": len({invoice.customer_id or invoice.customer_name for invoice in invoices}),
        "conversion": format_percent((completed / len(invoices) * 100) if invoices else None),
        "return_rate": format_percent((returns / len(invoices) * 100) if invoices else None),
        "avg_ticket_label": format_iqd(int(sales / len(live)) if live else 0),
        "sales": sales,
        "sales_label": format_iqd(sales),
        "messages": len(events),
        "waiting_messages": waiting,
        "late_messages": late,
        "answered_messages": answered,
        "reply_rate": format_percent((answered / len(events) * 100) if events else None),
        "avg_response": format_duration(int(sum(speeds) / len(speeds)) if speeds else None),
        "fastest": format_duration(min(speeds) if speeds else None),
        "slowest": format_duration(max(speeds) if speeds else None),
        "last_order_label": format_relative(last_order, now),
        "last_message_label": format_relative(last_message_at, now),
        "employees": staff,
        "range": preset,
        "range_label": range_labels.get(preset, "اليوم"),
    }


def ad_detail(ad_id: str, args: dict, *, now: datetime | None = None, tenant_id: int | None = None) -> dict | None:
    now = now or datetime.utcnow()
    ad_key = str(ad_id or "").strip()
    if not ad_key:
        return None
    snapshot = build_snapshot(
        {**args, "ad_id": ad_key, "page_id": "", "employee_id": "", "status": "", "limit": 1},
        now=now,
        tenant_id=tenant_id,
        tenant_slug=args.get("tenant_slug"),
        include_raw=True,
        skip_graph=True,
    )
    ranked = next((row for row in snapshot["ads"] if str(row.get("id")) == ad_key), None)
    if not ranked:
        return None
    events = snapshot.get("_events") or []
    invoices = list(snapshot.get("_invoices") or [])
    speeds = [
        event["response_seconds"]
        for event in events
        if event.get("response_seconds") is not None and event.get("status") in {"ANSWERED", "ORDER_CREATED", "CLOSED"}
    ]
    completed = sum(1 for invoice in invoices if _norm(invoice.status) in COMPLETED_STATUSES)
    returns = sum(1 for invoice in invoices if _norm(invoice.status) in RETURN_STATUSES)
    cancelled = sum(1 for invoice in invoices if _norm(invoice.status) in CANCELED_STATUSES)
    pending = sum(1 for invoice in invoices if _norm(invoice.status) in PENDING_STATUSES)
    live = [invoice for invoice in invoices if _norm(invoice.status) not in CANCELED_STATUSES]
    sales = sum(int(invoice.total or 0) for invoice in live)
    waiting = sum(1 for event in events if event.get("status") in {"NEW", "WAITING_REPLY"})
    late = sum(1 for event in events if event.get("status") == "LATE")
    answered = sum(1 for event in events if event.get("status") in {"ANSWERED", "ORDER_CREATED", "CLOSED"})
    last_order = max((invoice.created_at for invoice in invoices if invoice.created_at), default=None)
    last_message = max((event.get("received_at") for event in events if event.get("received_at")), default=None)
    last_message_at = None
    if last_message:
        try:
            last_message_at = datetime.fromisoformat(str(last_message).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            last_message_at = None
    staff = []
    seen = set()
    for invoice in invoices:
        emp_id = invoice.employee_id
        if not emp_id or emp_id in seen:
            continue
        employee = Employee.query.get(emp_id)
        if not employee:
            continue
        seen.add(emp_id)
        mine = [row for row in invoices if row.employee_id == emp_id]
        staff.append({
            "id": employee.id,
            "name": employee.name,
            "orders": len(mine),
            "sales": sum(int(row.total or 0) for row in mine if _norm(row.status) not in CANCELED_STATUSES),
            "sales_label": format_iqd(sum(int(row.total or 0) for row in mine if _norm(row.status) not in CANCELED_STATUSES)),
        })
    staff.sort(key=lambda row: (row["sales"], row["orders"]), reverse=True)
    range_labels = {
        "today": "اليوم",
        "yesterday": "أمس",
        "last_7": "آخر 7 أيام",
        "last_30": "آخر 30 يوم",
        "this_month": "هذا الشهر",
        "all": "الكل",
        "custom": "فترة محددة",
    }
    preset = snapshot.get("range") or parse_date_range(args.get("range"), args.get("from"), args.get("to"), now)[0]
    messages = max(int(ranked.get("messages") or 0), len(events))
    return {
        "id": ranked["id"],
        "name": ranked.get("name") or "إعلان فيسبوك",
        "page_name": ranked.get("page_name") or "",
        "thumbnail": ranked.get("thumbnail") or "",
        "initials": _initials(ranked.get("name") or "إعلان"),
        "active": ranked.get("active", True),
        "spend_label": ranked.get("spend_label") or "—",
        "cost_per_message_label": ranked.get("cost_per_message_label") or "—",
        "cost_per_order_label": ranked.get("cost_per_order_label") or "—",
        "orders": len(invoices),
        "completed": completed,
        "pending": pending,
        "returns": returns,
        "cancelled": cancelled,
        "customers": len({invoice.customer_id or invoice.customer_name for invoice in invoices}),
        "conversion": format_percent((completed / len(invoices) * 100) if invoices else None),
        "return_rate": format_percent((returns / len(invoices) * 100) if invoices else None),
        "avg_ticket_label": format_iqd(int(sales / len(live)) if live else 0),
        "sales": sales,
        "sales_label": format_iqd(sales),
        "messages": messages,
        "waiting_messages": waiting,
        "late_messages": late,
        "answered_messages": answered,
        "reply_rate": format_percent((answered / len(events) * 100) if events else None),
        "avg_response": format_duration(int(sum(speeds) / len(speeds)) if speeds else None),
        "fastest": format_duration(min(speeds) if speeds else None),
        "slowest": format_duration(max(speeds) if speeds else None),
        "last_order_label": format_relative(last_order, now),
        "last_message_label": format_relative(last_message_at, now),
        "employees": staff,
        "range": preset,
        "range_label": range_labels.get(preset, "اليوم"),
    }


def _events_for(args, *, now, tenant_id):
    snapshot_args = dict(args)
    snapshot_args["limit"] = 1
    # Reuse the same loader path without pagination by calling internal pieces.
    preset, start, end = parse_date_range(args.get("range"), args.get("from"), args.get("to"), now)
    channels = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CHANNEL_TYPES)).all()
    pages, _graph_error = _load_pages(channels, args.get("tenant_slug"))
    selected = next((page for page in pages if page["id"] == str(args.get("page_id") or "")), None)
    channel_ids = [selected["channel_id"]] if selected and selected["channel_id"] else [page["channel_id"] for page in pages if page["channel_id"]]
    inbound = _load_inbound(channel_ids, start, end)
    conversations = _load_conversations(inbound)
    outbound = _first_outbound_after(inbound)
    invoices = {row.id: row for row in _range_invoices(start, end, tenant_id)}
    events = [
        _message_event(message, conversations.get(message.conversation_id), outbound.get(message.id), invoices, pages, now)
        for message in inbound
    ]
    employee_id = _int_or_none(args.get("employee_id"))
    if selected:
        events = [event for event in events if event["page_id"] == selected["id"]]
    if employee_id:
        events = [event for event in events if event["employee_id"] == employee_id]
    return events


def _range_invoices(start, end, tenant_id):
    query = Invoice.query.filter(
        Invoice.deleted_at.is_(None),
        Invoice.created_at >= start,
        Invoice.created_at < end,
    )
    if tenant_id:
        query = query.filter(or_(Invoice.tenant_id == tenant_id, Invoice.tenant_id.is_(None)))
    return query.all()


def _load_employees(tenant_id):
    query = Employee.query.filter(Employee.is_active.is_(True))
    if tenant_id:
        query = query.filter(or_(Employee.tenant_id == tenant_id, Employee.tenant_id.is_(None)))
    return query.order_by(Employee.name.asc()).all()


def _load_inbound(channel_ids, start, end):
    if not channel_ids:
        return []
    return (
        AISalesMessage.query.filter(
            AISalesMessage.direction == "inbound",
            AISalesMessage.channel_account_id.in_(channel_ids),
            AISalesMessage.created_at >= start,
            AISalesMessage.created_at < end,
        )
        .order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc())
        .limit(MESSAGE_CAP)
        .all()
    )


def _load_open_inbound(channel_ids, before_start, exclude_ids: set | None = None):
    """Latest inbound for conversations still waiting for a reply, older than the filter start."""
    if not channel_ids or not before_start:
        return []
    waiting = (
        AISalesConversation.query.filter(
            AISalesConversation.channel_account_id.in_(channel_ids),
            AISalesConversation.status != "closed",
            AISalesConversation.last_customer_message_at.isnot(None),
            AISalesConversation.last_customer_message_at < before_start,
            or_(
                AISalesConversation.last_business_message_at.is_(None),
                AISalesConversation.last_customer_message_at > AISalesConversation.last_business_message_at,
            ),
        )
        .order_by(AISalesConversation.last_customer_message_at.desc())
        .limit(150)
        .all()
    )
    if not waiting:
        return []
    skip = exclude_ids or set()
    latest = []
    for conversation in waiting:
        message = (
            AISalesMessage.query.filter(
                AISalesMessage.conversation_id == conversation.id,
                AISalesMessage.direction == "inbound",
            )
            .order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc())
            .first()
        )
        if message and message.id not in skip:
            latest.append(message)
    return latest


def _load_conversations(inbound):
    ids = {message.conversation_id for message in inbound}
    if not ids:
        return {}
    rows = AISalesConversation.query.filter(AISalesConversation.id.in_(ids)).all()
    return {row.id: row for row in rows}


def _safe_avatar(url: str | None) -> str:
    value = str(url or "")
    if not value or "fbcdn.net" in value or "facebook.com" in value:
        return ""
    return value


def _facebook_pic_hint(url: str | None) -> str:
    value = str(url or "").strip()
    host = value.lower()
    if not value.startswith("https://"):
        return ""
    if not any(part in host for part in ("fbcdn.net", "facebook.com", "fbsbx.com", "fb.com")):
        return ""
    return value


def _participant_picture(person: dict | None) -> str:
    picture = (person or {}).get("picture") or {}
    data = picture.get("data") if isinstance(picture, dict) else {}
    if not isinstance(data, dict) or data.get("is_silhouette"):
        return ""
    return _facebook_pic_hint(data.get("url"))


def _customer_avatar_url(
    external_page_id: str | None,
    customer_psid: str | None,
    name: str | None = "",
    pic_url: str | None = "",
) -> str:
    from urllib.parse import quote

    page_id = "".join(ch for ch in str(external_page_id or "") if ch.isdigit())
    psid = "".join(ch for ch in str(customer_psid or "") if ch.isdigit())
    if not page_id or not psid:
        return ""
    letter = _initials(name)[:1] or "ف"
    hint = _facebook_pic_hint(pic_url)
    extra = f"&src={quote(hint, safe='')}" if hint else ""
    return f"/api/facebook-monitor/customer-avatar?page_id={page_id}&psid={psid}&letter={quote(letter)}{extra}"


def _page_avatar_url(external_page_id: str | None) -> str:
    page_id = "".join(ch for ch in str(external_page_id or "") if ch.isdigit())
    if not page_id:
        return ""
    return f"/api/facebook-monitor/page-avatar/{page_id}"


def _load_pages(channels, tenant_slug: str | None) -> tuple[list[dict], str]:
    stored = _pages_from_stored_tokens()
    if stored:
        return _attach_channels(stored, channels), ""
    if _graph_cooling():
        try:
            publishers = PublisherPage.query.order_by(PublisherPage.page_name.asc()).all()
        except Exception:
            publishers = []
        return _merge_pages(channels, publishers), _LIMIT_HINT
    graph_pages, error = _graph_pages(tenant_slug)
    if graph_pages:
        return _attach_channels(graph_pages, channels), ""
    try:
        publishers = PublisherPage.query.order_by(PublisherPage.page_name.asc()).all()
    except Exception:
        publishers = []
    fallback = _merge_pages(channels, publishers)
    return fallback, error or ("لا توجد صفحات من فيسبوك حالياً." if not fallback else "")


def _graph_pages(tenant_slug: str | None) -> tuple[list[dict], str]:
    import requests

    from modules.publisher.models.publisher_settings import PublisherSettings
    from modules.publisher.services.token_utils import decrypt_token

    settings = None
    try:
        from modules.publisher.services.schema_guard import ensure_publisher_schema
        try:
            ensure_publisher_schema(force=True)
        except TypeError:
            ensure_publisher_schema()
        if tenant_slug:
            settings = PublisherSettings.query.filter_by(tenant_slug=tenant_slug).first()
        if not settings or not settings.fb_user_token:
            settings = PublisherSettings.query.filter(PublisherSettings.fb_user_token.isnot(None)).first()
    except Exception:
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        settings = None
    token = ""
    if settings and settings.fb_user_token:
        token = decrypt_token(settings.fb_user_token)
    if not token:
        token = _meta_user_token()
    if not token:
        return [], "لا يوجد رمز فيسبوك محفوظ لجلب الصفحات من API."

    url = f"{GRAPH_BASE}/me/accounts"
    params = {"access_token": token, "fields": "id,name,picture{url},access_token", "limit": 100}
    pages = []
    try:
        while url:
            response = requests.get(url, params=params, timeout=8)
            payload = response.json()
            if payload.get("error"):
                err = payload.get("error") or {}
                if _is_limit_error(err):
                    return [], _mark_graph_limit()
                message = err.get("message") or "تعذر جلب الصفحات من فيسبوك."
                return [], message
            for row in payload.get("data") or []:
                page_id = str(row.get("id") or "")
                pages.append({
                    "id": f"fb:{page_id}",
                    "channel_id": None,
                    "publisher_id": None,
                    "name": row.get("name") or "صفحة فيسبوك",
                    "avatar": "",
                    "external_page_id": page_id,
                    "_token": row.get("access_token") or "",
                    "last_webhook_at": None,
                    "last_error": "",
                })
            url = ((payload.get("paging") or {}).get("next") or "")
            params = None
    except Exception as exc:
        return [], str(exc)
    return pages, ""


def _pages_from_stored_tokens() -> list[dict]:
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token

    pages = []
    try:
        rows = PublisherPage.query.filter(PublisherPage.page_token.isnot(None)).all()
    except Exception:
        return []
    for row in rows:
        token = decrypt_token(row.page_token or "")
        if not token or not row.page_id:
            continue
        pages.append({
            "id": f"publisher:{row.id}",
            "channel_id": None,
            "publisher_id": row.id,
            "name": row.page_name or "صفحة فيسبوك",
            "avatar": "",
            "external_page_id": str(row.page_id),
            "_token": token,
            "connected": True,
            "last_webhook_at": None,
            "last_error": "",
        })
    return pages


def _apply_page_tokens(pages, tenant_slug: str | None) -> None:
    missing = [page for page in pages if not page.get("_token") and page.get("external_page_id")]
    if not missing:
        return
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token

    rows = PublisherPage.query.filter(PublisherPage.page_id.in_([page["external_page_id"] for page in missing])).all()
    if tenant_slug:
        scoped = [row for row in rows if row.tenant_slug in {tenant_slug, "default", None, ""}]
        if scoped:
            rows = scoped
    by_id = {str(row.page_id): decrypt_token(row.page_token) for row in rows if row.page_token}
    for page in missing:
        page["_token"] = by_id.get(page["external_page_id"]) or ""


def _parse_fb_time(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def clear_graph_cache():
    _GRAPH_CACHE.clear()


def apply_local_replies(events, now) -> None:
    """Graph rows stay LATE until Facebook refreshes. Local employee replies mark them answered now."""
    if not events:
        return
    from modules.ai_sales.models import AISalesMessage
    from modules.facebook_routing.engine import conversation_for_psid

    for event in events:
        page_id = str(event.get("external_page_id") or "").strip()
        psid = str(event.get("customer_psid") or "").strip()
        if not page_id or not psid:
            continue
        conversation = conversation_for_psid(page_id, psid)
        if not conversation:
            continue
        last_out = (
            AISalesMessage.query.filter_by(conversation_id=conversation.id, direction="outbound")
            .order_by(AISalesMessage.created_at.desc())
            .first()
        )
        answered_at = conversation.last_business_message_at or (last_out.created_at if last_out else None)
        received_at = _parse_fb_time(event.get("received_at"))
        if event.get("received_at") and not received_at:
            try:
                received_at = datetime.fromisoformat(str(event["received_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                received_at = None
        stored_pic = conversation.contact_profile_picture_url or ""
        avatar = str(event.get("customer_avatar") or "")
        from urllib.parse import parse_qs, unquote, urlparse

        src = unquote((parse_qs(urlparse(avatar).query).get("src") or [""])[0])
        if src and src != stored_pic:
            conversation.contact_profile_picture_url = src[:800]
        elif stored_pic and "src=" not in avatar:
            event["customer_avatar"] = _customer_avatar_url(page_id, psid, event.get("customer_name"), stored_pic)
        out_text = (last_out.text_content or "").strip() if last_out else ""
        if out_text and answered_at and received_at and answered_at >= received_at:
            event["preview"] = _preview_line(out_text, outbound=True)
        else:
            event["preview"] = _preview_line(event.get("preview") or "", outbound=False)
        if not answered_at:
            continue
        if event.get("status") in {"ANSWERED", "ORDER_CREATED", "CLOSED"}:
            continue
        if not received_at or answered_at < received_at:
            continue
        status, seconds = classify_message(
            received_at=received_at,
            answered_at=answered_at,
            now=now,
            has_order=bool(event.get("order_id")),
            conversation_closed=str(getattr(conversation, "status", "") or "") == "closed",
        )
        event["status"] = status
        event["status_label"] = STATUS_LABELS.get(status, status)
        event["response_seconds"] = seconds
        event["response_label"] = format_duration(seconds)
        event["response_tone"] = response_tone(seconds, waiting=False)
        event["unread_count"] = 0
    try:
        from extensions import db

        db.session.commit()
    except Exception:
        db.session.rollback()


def apply_unread_counts(events) -> None:
    if not events:
        return
    from flask import session
    from modules.ai_sales.models import AISalesConversationRead, AISalesMessage
    from modules.facebook_routing.engine import conversation_for_psid

    employee_id = session.get("user_id")
    waiting = {"NEW", "WAITING_REPLY", "LATE"}
    for event in events:
        page_id = str(event.get("external_page_id") or "").strip()
        psid = str(event.get("customer_psid") or "").strip()
        graph_unread = int(event.get("unread_count") or 0)
        if not page_id or not psid:
            if event.get("status") in waiting and graph_unread < 1:
                event["unread_count"] = 1
            continue
        conversation = conversation_for_psid(page_id, psid)
        if not conversation:
            if event.get("status") in waiting and graph_unread < 1:
                event["unread_count"] = 1
            continue
        last_out = (
            AISalesMessage.query.filter_by(conversation_id=conversation.id, direction="outbound")
            .order_by(AISalesMessage.created_at.desc())
            .first()
        )
        last_read_at = None
        if employee_id:
            receipt = AISalesConversationRead.query.filter_by(
                conversation_id=conversation.id, employee_id=employee_id
            ).first()
            last_read_at = receipt.last_read_at if receipt else None
        cutoff = None
        for moment in (last_out.created_at if last_out else None, last_read_at):
            if moment and (cutoff is None or moment > cutoff):
                cutoff = moment
        query = AISalesMessage.query.filter_by(conversation_id=conversation.id, direction="inbound")
        local_total = query.count()
        if cutoff:
            local_unread = query.filter(AISalesMessage.created_at > cutoff).count()
        else:
            local_unread = local_total
        if local_total:
            event["unread_count"] = local_unread
        elif cutoff and event.get("status") in {"ANSWERED", "ORDER_CREATED", "CLOSED"}:
            event["unread_count"] = 0
        elif event.get("status") in waiting:
            event["unread_count"] = max(graph_unread, 1)
        else:
            event["unread_count"] = graph_unread


def _human_graph_error(message: str) -> str:
    import re

    text = str(message or "").strip()
    low = text.lower()
    if "session has expired" in low or "error validating access token" in low or "invalid oauth" in low:
        when = ""
        match = re.search(r"expired on ([^.]+)", text, re.I)
        if match:
            when = match.group(1).strip()
        stamp = f" ({when})" if when else ""
        return (
            f"رمز فيسبوك انتهى{stamp}. "
            "من الإعدادات ← الصفحات الصق رمز صفحة جديد من Meta، ثم اضغط جلب الآن."
        )
    return text


def _is_limit_error(err) -> bool:
    if isinstance(err, dict):
        code = err.get("code")
        message = str(err.get("message") or "")
    else:
        code = None
        message = str(err or "")
    return code == 4 or "request limit" in message.lower()


def _cooldown_file() -> str:
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    folder = os.path.join(root, "tmp")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        folder = os.environ.get("TMP") or os.environ.get("TEMP") or "/tmp"
    return os.path.join(folder, "facebook_graph_cooldown")


def _cooldown_until() -> float:
    until = _GRAPH_COOLDOWN_UNTIL
    try:
        with open(_cooldown_file(), "r", encoding="utf-8") as handle:
            until = max(until, float((handle.read() or "0").strip() or 0))
    except Exception:
        pass
    return until


def _graph_cooling() -> bool:
    import time

    return time.time() < _cooldown_until()


def _mark_graph_limit() -> str:
    import time

    global _GRAPH_COOLDOWN_UNTIL
    until = time.time() + _GRAPH_COOLDOWN_SEC
    _GRAPH_COOLDOWN_UNTIL = until
    try:
        with open(_cooldown_file(), "w", encoding="utf-8") as handle:
            handle.write(str(until))
    except Exception:
        pass
    return _LIMIT_HINT


def _pull_file() -> str:
    import os

    return os.path.join(os.path.dirname(_cooldown_file()), "facebook_pull.json")


def facebook_pull_status() -> dict:
    import json

    raw = {}
    try:
        with open(_pull_file(), "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            if isinstance(loaded, dict):
                raw = loaded
    except Exception:
        raw = {}
    try:
        limit = int(raw.get("limit") or 25)
    except (TypeError, ValueError):
        limit = 25
    limit = max(8, min(50, limit))
    try:
        pulled = int(raw.get("pulled") or 0)
    except (TypeError, ValueError):
        pulled = 0
    return {
        "limit": limit,
        "pulled": pulled,
        "pages": int(raw.get("pages") or 0),
        "error": _human_graph_error(str(raw.get("error") or "")),
        "at": str(raw.get("at") or ""),
    }


def _save_pull_status(**fields) -> dict:
    import json

    current = facebook_pull_status()
    current.update(fields)
    current["limit"] = max(8, min(50, int(current.get("limit") or 25)))
    try:
        with open(_pull_file(), "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False)
    except Exception:
        pass
    return current


def _assign_recent_unassigned(limit: int = 200) -> int:
    """Hand past-week unassigned Messenger threads to eligible employees."""
    try:
        from modules.facebook_routing.engine import drain_unassigned_queue
        from extensions import db

        since = datetime.utcnow() - timedelta(days=7)
        # Past-day recovery must ignore full caps; otherwise backlog never moves.
        assigned = drain_unassigned_queue(
            None,
            limit=max(int(limit or 200), 200),
            since=since,
            ignore_capacity=True,
        )
        if assigned:
            db.session.commit()
        return int(assigned or 0)
    except Exception:
        try:
            from extensions import db

            db.session.rollback()
        except Exception:
            pass
        return 0


def pull_facebook_conversations(limit: int) -> dict:
    """Import recent Messenger threads into local conversations. One Graph call per page."""
    import requests

    from extensions import db
    from modules.ai_sales.engine import get_or_create_conversation
    from modules.ai_sales.models import AISalesChannelAccount, AISalesMessage

    limit = max(8, min(50, int(limit or 25)))
    if _graph_cooling():
        status = _save_pull_status(limit=limit, error=_LIMIT_HINT)
        status["ok"] = False
        status["assigned"] = _assign_recent_unassigned(limit)
        return status
    pages = [page for page in _pages_from_stored_tokens() if page.get("_token") and page.get("external_page_id")]
    enabled_ids, enabled_names = _routing_lookup()
    if enabled_ids or enabled_names:
        chosen = []
        for page in pages:
            ext = str(page.get("external_page_id") or "")
            if ext in enabled_ids or (_norm(page.get("name")) in enabled_names and _norm(page.get("name"))):
                chosen.append(page)
        if chosen:
            pages = chosen
    stored = 0
    used_pages = 0
    error = ""
    for page in pages:
        if stored >= limit or used_pages >= 8 or _graph_cooling():
            break
        page_id = str(page["external_page_id"])
        channel = AISalesChannelAccount.query.filter(
            AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
            AISalesChannelAccount.page_id == page_id,
        ).first()
        if not channel:
            continue
        ask = min(25, limit - stored)
        try:
            response = requests.get(
                f"{GRAPH_BASE}/{page_id}/conversations",
                params={
                    "platform": "messenger",
                    "access_token": page["_token"],
                    "limit": ask,
                    "fields": "updated_time,snippet,participants{id,name},messages.limit(2){id,message,from{id,name},created_time}",
                },
                timeout=12,
            )
            payload = response.json()
        except Exception as exc:
            error = str(exc)
            break
        used_pages += 1
        err = payload.get("error") or {}
        if err:
            if _is_limit_error(err):
                error = _mark_graph_limit()
            else:
                error = _human_graph_error(err.get("message") or "فيسبوك رفض جلب المحادثات.")
            break
        for thread in payload.get("data") or []:
            if stored >= limit:
                break
            if _store_pulled_thread(channel, page_id, thread, get_or_create_conversation, AISalesMessage):
                stored += 1
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        error = error or str(exc)
        stored = 0
    assigned = 0
    try:
        assigned = _assign_recent_unassigned(max(limit, 200))
    except Exception:
        assigned = 0
    status = _save_pull_status(
        limit=limit,
        pulled=stored,
        pages=used_pages,
        error=error,
        at=datetime.utcnow().isoformat(),
    )
    status["ok"] = not error
    status["assigned"] = assigned
    return status


def _store_pulled_thread(channel, page_id: str, thread: dict, get_or_create_conversation, message_model) -> bool:
    from extensions import db
    messages = ((thread.get("messages") or {}).get("data") or [])
    inbound = None
    inbound_at = None
    for item in messages:
        sender = str(((item.get("from") or {}).get("id") or ""))
        if sender == page_id:
            continue
        moment = _parse_fb_time(item.get("created_time")) or _parse_fb_time(thread.get("updated_time"))
        if inbound_at is None or (moment and moment >= inbound_at):
            inbound = item
            inbound_at = moment
    if inbound is None:
        return False
    participants = ((thread.get("participants") or {}).get("data") or [])
    customer = next((person for person in participants if str(person.get("id") or "") != page_id), None) or {}
    psid = str(customer.get("id") or ((inbound.get("from") or {}).get("id") or ""))
    if not psid or psid == page_id:
        return False
    external_id = str(inbound.get("id") or "")
    if external_id and message_model.query.filter_by(channel_account_id=channel.id, external_message_id=external_id).first():
        return False
    name = str(customer.get("name") or ((inbound.get("from") or {}).get("name") or "") or "")
    conversation = get_or_create_conversation(
        channel,
        external_contact_id=psid,
        phone="",
        contact_name=name,
        route_facebook=True,
    )
    text = str(inbound.get("message") or thread.get("snippet") or "").strip()
    when = inbound_at or datetime.utcnow()
    db.session.add(message_model(
        conversation_id=conversation.id,
        channel_account_id=channel.id,
        external_message_id=external_id or None,
        direction="inbound",
        sender_type="customer",
        message_type="text",
        text_content=text or None,
        status="received",
        created_at=when,
    ))
    if not conversation.last_customer_message_at or when >= conversation.last_customer_message_at:
        conversation.last_customer_message_at = when
    conversation.updated_at = when
    if text:
        conversation.summary = text[:300]
    return True


def _ads_disk_path() -> str:
    import os

    return os.path.join(os.path.dirname(_cooldown_file()), "facebook_ads_cache.json")


def _ads_disk_load() -> tuple[list, str] | None:
    import json

    try:
        with open(_ads_disk_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        ads = data.get("ads") if isinstance(data, dict) else None
        if not isinstance(ads, list):
            return None
        return ads, str(data.get("error") or "")
    except Exception:
        return None


def _ads_disk_save(ads: list, error: str = "") -> None:
    import json

    try:
        with open(_ads_disk_path(), "w", encoding="utf-8") as handle:
            json.dump({"ads": ads, "error": error}, handle, ensure_ascii=False)
    except Exception:
        pass


def _routing_lookup() -> tuple[set[str], set[str]]:
    """Ids and names of pages whose distribution switch is on."""
    ids: set[str] = set()
    names: set[str] = set()
    try:
        from modules.facebook_routing.engine import page_key
        from modules.facebook_routing.models import FacebookPageRouting

        rows = FacebookPageRouting.query.filter_by(routing_enabled=True).all()
    except Exception:
        return ids, names
    for row in rows:
        if row.page_id:
            ids.add(str(row.page_id))
    if not ids:
        return ids, names
    try:
        channels = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CHANNEL_TYPES)).all()
    except Exception:
        channels = []
    for channel in channels:
        key = page_key(channel)
        linked = key in ids or str(channel.page_id or "") in ids or str(channel.external_account_id or "") in ids
        if not linked:
            continue
        if channel.page_id:
            ids.add(str(channel.page_id))
        if channel.name:
            names.add(_norm(channel.name))
    try:
        from modules.publisher.models.publisher_page import PublisherPage

        for row in PublisherPage.query.filter(PublisherPage.page_id.in_(list(ids))).all():
            if row.page_id:
                ids.add(str(row.page_id))
            if row.page_name:
                names.add(_norm(row.page_name))
    except Exception:
        pass
    names.discard("")
    return ids, names


def _graph_cache_get(key):
    import time

    hit = _GRAPH_CACHE.get(key)
    if not hit or time.time() - hit[0] > _GRAPH_CACHE_TTL:
        return None
    pages, events, error = hit[1], hit[2], hit[3]
    return [dict(page) for page in pages], list(events), error


def _graph_cache_set(key, pages, events, error):
    import time

    _GRAPH_CACHE[key] = (time.time(), [dict(page) for page in pages], list(events), error)


def _fetch_page_threads(page):
    import requests

    response = requests.get(
        f"{GRAPH_BASE}/{page['external_page_id']}/conversations",
        params={
            "platform": "messenger",
            "access_token": page["_token"],
            "limit": 8,
            "fields": "updated_time,snippet,participants{id,name},messages.limit(4){id,message,from{id,name},created_time}",
        },
        timeout=8,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"error": {"message": f"HTTP {response.status_code}"}}
    return page, payload


def _graph_message_events(pages, start, end, now) -> tuple[list[dict], str]:
    if _graph_cooling():
        return [], _LIMIT_HINT
    targets = [page for page in pages if page.get("_token") and page.get("external_page_id")]
    if not targets:
        return [], ""
    enabled, _enabled_names = _routing_lookup()
    if enabled:
        targets = [page for page in targets if page.get("external_page_id") in enabled]
    targets = targets[:2]
    events = []
    denied = 0
    other_error = ""
    try:
        for page in targets:
            try:
                page, payload = _fetch_page_threads(page)
            except Exception as exc:
                other_error = other_error or str(exc)
                continue
            err = payload.get("error") or {}
            if err:
                if _is_limit_error(err):
                    return events, _mark_graph_limit()
                code = err.get("code")
                message = err.get("message") or ""
                if code == 200 or "#200" in message or "appropriate role" in message.lower():
                    denied += 1
                else:
                    other_error = other_error or message or "تعذر جلب رسائل فيسبوك."
                continue
            for thread in payload.get("data") or []:
                event = _graph_thread_event(page, thread, start, end, now)
                if event:
                    events.append(event)
    except Exception as exc:
        other_error = other_error or str(exc)

    if events:
        if denied:
            return events, f"تم تخطي {denied} صفحة بلا صلاحية رسائل."
        return events, ""
    if denied and not other_error:
        return [], (
            f"ماكو صلاحية رسائل على {denied} صفحة. "
            "استخدم User Token لحساب Admin على الصفحات، "
            "واختر صلاحيات pages_messaging و pages_show_list، ثم اضغط حفظ وربط الصفحات."
        )
    return [], other_error


def _referral_from_thread(messages: list[dict]) -> dict:
    for item in messages or []:
        referral = item.get("referral") or {}
        ads_data = referral.get("ads_context_data") or {}
        ad_id = str(referral.get("ad_id") or ads_data.get("ad_id") or "").strip()
        if ad_id or referral.get("source") == "ADS" or ads_data:
            return {
                "ad_id": ad_id,
                "title": str(ads_data.get("ad_title") or ads_data.get("post_id") or referral.get("ref") or "").strip(),
                "source": str(referral.get("source") or ""),
            }
    return {}


def _graph_thread_event(page, thread, start, end, now):
    messages = ((thread.get("messages") or {}).get("data") or [])
    parsed = []
    for item in messages:
        moment = _parse_fb_time(item.get("created_time"))
        if moment:
            parsed.append((moment, item))
    parsed.sort(key=lambda pair: pair[0])
    page_id = str(page.get("external_page_id") or "")
    inbound = [(moment, item) for moment, item in parsed if str(((item.get("from") or {}).get("id") or "")) != page_id]
    if not inbound and thread.get("snippet"):
        moment = _parse_fb_time(thread.get("updated_time"))
        if moment:
            inbound = [(moment, {"id": thread.get("id"), "message": thread.get("snippet"), "from": {}})]
    if not inbound:
        return None
    received_at, latest = inbound[-1]
    if received_at < start or received_at >= end:
        return None
    answered_at = next((moment for moment, item in parsed if moment >= received_at and str(((item.get("from") or {}).get("id") or "")) == page_id), None)
    last_page_at = max((moment for moment, item in parsed if str(((item.get("from") or {}).get("id") or "")) == page_id), default=None)
    unread_count = sum(1 for moment, _ in inbound if not last_page_at or moment > last_page_at)
    if not answered_at and unread_count < 1:
        unread_count = 1
    if answered_at:
        unread_count = 0
    status, seconds = classify_message(received_at=received_at, answered_at=answered_at, now=now)
    participants = ((thread.get("participants") or {}).get("data") or [])
    customer_person = next((person for person in participants if str(person.get("id") or "") != page_id), None) or {}
    customer = str(customer_person.get("name") or ((latest.get("from") or {}).get("name") or "") or "عميل فيسبوك")
    customer_psid = str(customer_person.get("id") or "")
    if not customer_psid:
        from_id = str(((latest.get("from") or {}).get("id") or ""))
        if from_id and from_id != page_id:
            customer_psid = from_id
    last_item = parsed[-1][1] if parsed else latest
    last_is_page = str(((last_item.get("from") or {}).get("id") or "")) == page_id
    inbound_from = next((item.get("from") for _, item in reversed(parsed) if str(((item.get("from") or {}).get("id") or "")) != page_id), latest.get("from"))
    pic = _participant_picture(customer_person) or _participant_picture(inbound_from)
    preview = _preview_line(
        (last_item.get("message") or latest.get("message") or thread.get("snippet") or "").strip(),
        outbound=last_is_page,
    )
    waiting = status in {"NEW", "WAITING_REPLY", "LATE"}
    referral = _referral_from_thread([item for _, item in parsed] + [latest])
    campaign = referral.get("title") or ""
    ad_id = referral.get("ad_id") or ""
    source = "إعلان فيسبوك" if (ad_id or referral.get("source") == "ADS") else "Facebook Messenger"
    thread_id = str(thread.get("id") or "")
    return {
        "id": latest.get("id") or thread.get("id"),
        "thread_id": thread_id,
        "external_page_id": page_id,
        "customer_psid": customer_psid,
        "can_open": bool(thread_id and page_id),
        "page_id": page["id"],
        "page_name": page["name"],
        "page_avatar": page.get("avatar") or "",
        "page_initials": _initials(page["name"]),
        "customer_name": customer,
        "customer_avatar": _customer_avatar_url(page_id, customer_psid, customer, pic),
        "customer_initials": _initials(customer),
        "preview": preview,
        "source": source,
        "campaign": campaign,
        "ad_id": ad_id,
        "received_at": received_at.isoformat(),
        "time_label": format_relative(received_at, now),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "response_seconds": seconds,
        "response_label": format_duration(seconds),
        "response_tone": response_tone(seconds, waiting=waiting),
        "employee_id": None,
        "employee_name": "",
        "assigned_employee_id": None,
        "assignment_status": "UNASSIGNED",
        "order_id": None,
        "order_label": "",
        "order_total_label": "",
        "order_after": "",
        "attribution": "UNATTRIBUTED",
        "phone": "",
        "unread_count": unread_count,
        "search_text": " ".join(filter(None, [customer, preview, page["name"], campaign, ad_id])).lower(),
    }


def _ensure_page_routing(page_id: str) -> None:
    """A connected page stays active unless distribution was switched off on purpose."""
    if not page_id:
        return
    try:
        from extensions import db
        from modules.facebook_routing.models import FacebookPageRouting
        from modules.facebook_routing.schema import ensure_facebook_routing_schema

        ensure_facebook_routing_schema()
        row = FacebookPageRouting.query.filter_by(page_id=page_id).first()
        if row and not row.routing_enabled and (row.routing_method or "") == "MANUAL_OFF":
            return
        if not row:
            row = FacebookPageRouting(page_id=page_id, routing_enabled=True, routing_method="LEAST_ACTIVE")
            db.session.add(row)
        elif not row.routing_enabled:
            row.routing_enabled = True
            row.routing_method = "LEAST_ACTIVE"
        else:
            return
        db.session.commit()
    except Exception:
        db.session.rollback()


def _meta_user_token() -> str:
    from modules.ai_sales.security import decrypt_secret

    connector = AISalesChannelAccount.query.filter_by(channel_type="meta").order_by(AISalesChannelAccount.id.desc()).first()
    if not connector or not connector.access_token_encrypted:
        return ""
    try:
        return decrypt_secret(connector.access_token_encrypted) or ""
    except Exception:
        return ""


def _attach_channels(pages: list[dict], channels) -> list[dict]:
    by_external = {}
    by_name = {}
    for channel in channels:
        if channel.page_id:
            by_external[str(channel.page_id)] = channel
        by_name.setdefault(_norm(channel.name), channel)
    for page in pages:
        channel = by_external.get(page["external_page_id"]) or by_name.get(_norm(page["name"]))
        if not channel:
            continue
        page["channel_id"] = channel.id
        page["last_webhook_at"] = channel.last_webhook_at
        page["last_error"] = channel.last_error or ""
        page["connected"] = bool(
            page.get("_token")
            or page.get("connected")
            or (
                channel.is_active
                and channel.access_token_encrypted
                and channel.connection_status in {"connected", "ready"}
            )
        )
        if not page["avatar"]:
            page["avatar"] = _safe_avatar(channel.profile_picture_url)
        if page.get("connected"):
            _ensure_page_routing(str(page.get("external_page_id") or ""))
    return pages


def _merge_pages(channels, publishers) -> list[dict]:
    pages = []
    seen = set()
    for channel in channels:
        key = _norm(channel.name)
        seen.add(key)
        pages.append({
            "id": f"channel:{channel.id}",
            "channel_id": channel.id,
            "publisher_id": None,
            "name": channel.name or "صفحة فيسبوك",
            "avatar": _page_avatar_url(channel.page_id) or _safe_avatar(channel.profile_picture_url),
            "external_page_id": channel.page_id or "",
            "last_webhook_at": channel.last_webhook_at,
            "last_error": channel.last_error or "",
        })
    for publisher in publishers:
        key = _norm(publisher.page_name)
        if key in seen:
            for page in pages:
                if _norm(page["name"]) == key and not page["publisher_id"]:
                    page["publisher_id"] = publisher.id
                    page["external_page_id"] = page["external_page_id"] or publisher.page_id
            continue
        pages.append({
            "id": f"publisher:{publisher.id}",
            "channel_id": None,
            "publisher_id": publisher.id,
            "name": publisher.page_name or "صفحة فيسبوك",
            "avatar": _page_avatar_url(publisher.page_id),
            "external_page_id": publisher.page_id or "",
            "last_webhook_at": None,
            "last_error": "",
        })
    return pages


def _first_outbound_after(inbound) -> dict:
    if not inbound:
        return {}
    conversation_ids = {message.conversation_id for message in inbound}
    earliest = min((message.created_at for message in inbound if message.created_at), default=None)
    if not earliest:
        return {}
    outbound = (
        AISalesMessage.query.filter(
            AISalesMessage.direction == "outbound",
            AISalesMessage.conversation_id.in_(conversation_ids),
            AISalesMessage.created_at >= earliest,
        )
        .order_by(AISalesMessage.created_at.asc())
        .all()
    )
    grouped: dict[int, list] = {}
    for message in outbound:
        if message.created_at:
            grouped.setdefault(message.conversation_id, []).append(message.created_at)
    found = {}
    for message in inbound:
        if not message.created_at:
            continue
        for moment in grouped.get(message.conversation_id, []):
            if moment >= message.created_at:
                found[message.id] = moment
                break
    return found


def _page_for_channel(pages, channel_id):
    return next((page for page in pages if page["channel_id"] == channel_id), None)


def _page_match(invoice, page) -> bool:
    if not page:
        return False
    return _norm(invoice.page_name) == _norm(page["name"])


def _message_event(message, conversation, answered_at, invoice_by_id, pages, now) -> dict:
    page = _page_for_channel(pages, message.channel_account_id)
    order_id = _loads_order_id(conversation)
    invoice = invoice_by_id.get(order_id) if order_id else None
    confidence = "UNATTRIBUTED"
    if invoice and order_id:
        confidence = "DIRECT"
    elif conversation and conversation.customer_id and page:
        candidate = _high_confidence_invoice(conversation, page, message.created_at, invoice_by_id.values())
        if candidate:
            invoice = candidate
            confidence = "HIGH"
    status, seconds = classify_message(
        received_at=message.created_at,
        answered_at=answered_at,
        now=now,
        has_order=bool(invoice),
        conversation_closed=bool(conversation and conversation.status == "closed"),
    )
    ad = _ad_context(conversation, message)
    employee_id = None
    employee_name = ""
    if invoice and invoice.employee_id:
        employee_id = invoice.employee_id
        employee_name = invoice.employee_name or ""
    elif conversation and conversation.assigned_employee_id:
        employee_id = conversation.assigned_employee_id
        employee_name = conversation.assigned_employee.name if conversation.assigned_employee else ""
    waiting = status in {"NEW", "WAITING_REPLY", "LATE"}
    customer = conversation.contact_name if conversation and conversation.contact_name else "عميل فيسبوك"
    preview = _preview_line((message.text_content or message.transcription or "").strip(), outbound=False)
    phone = (conversation.external_phone if conversation else "") or ""
    order_label = f"ORD-{invoice.id}" if invoice else ""
    after = ""
    if invoice and invoice.created_at and message.created_at and invoice.created_at >= message.created_at:
        gap = int((invoice.created_at - message.created_at).total_seconds())
        after = format_duration(gap)
    return {
        "id": message.id,
        "thread_id": "",
        "external_page_id": page.get("external_page_id") if page else "",
        "customer_psid": (conversation.external_contact_id if conversation else "") or "",
        "can_open": bool(conversation and conversation.external_contact_id and page and page.get("external_page_id")),
        "ai_conversation_id": conversation.id if conversation else None,
        "page_id": page["id"] if page else "",
        "page_name": page["name"] if page else "فيسبوك",
        "page_avatar": page["avatar"] if page else "",
        "page_initials": _initials(page["name"] if page else "ف"),
        "customer_name": customer,
        "customer_avatar": _customer_avatar_url(
            page.get("external_page_id") if page else "",
            (conversation.external_contact_id if conversation else "") or "",
            customer,
            conversation.contact_profile_picture_url if conversation else "",
        ),
        "customer_initials": _initials(customer),
        "preview": preview,
        "source": "Facebook Messenger",
        "campaign": ad.get("title") or ad.get("ref") or "",
        "ad_id": str(ad.get("ad_id") or ""),
        "received_at": message.created_at.isoformat() if message.created_at else "",
        "time_label": format_relative(message.created_at, now),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "response_seconds": seconds,
        "response_label": format_duration(seconds),
        "response_tone": response_tone(seconds, waiting=waiting),
        "employee_id": employee_id,
        "employee_name": employee_name,
        "assigned_employee_id": conversation.assigned_employee_id if conversation else None,
        "assignment_status": "ASSIGNED" if conversation and conversation.assigned_employee_id else "UNASSIGNED",
        "order_id": invoice.id if invoice else None,
        "order_label": order_label,
        "order_total_label": format_iqd(invoice.total) if invoice else "",
        "order_after": after,
        "attribution": confidence if invoice else "UNATTRIBUTED",
        "phone": phone,
        "unread_count": 1 if waiting else 0,
        "search_text": " ".join(filter(None, [
            customer, preview, order_label, phone, employee_name,
            page["name"] if page else "", ad.get("title") or "",
        ])).lower(),
    }


def _high_confidence_invoice(conversation, page, received_at, invoices):
    if not received_at:
        return None
    window = timedelta(hours=6)
    matches = []
    for invoice in invoices:
        if invoice.customer_id != conversation.customer_id or not _page_match(invoice, page) or not invoice.created_at:
            continue
        if received_at <= invoice.created_at <= received_at + window:
            matches.append(invoice)
    return matches[0] if len(matches) == 1 else None


def _status_counts(events) -> dict:
    counts = {"ALL": len(events), "NEW": 0, "WAITING_REPLY": 0, "LATE": 0, "ANSWERED": 0, "ORDER_CREATED": 0, "CLOSED": 0}
    for event in events:
        counts[event["status"]] = counts.get(event["status"], 0) + 1
    return counts


def _cursor_page(events, cursor, limit):
    start_index = 0
    if cursor:
        for index, event in enumerate(events):
            if str(event["id"]) == cursor:
                start_index = index + 1
                break
    chunk = events[start_index:start_index + limit]
    next_cursor = str(chunk[-1]["id"]) if chunk and len(events) > start_index + limit else ""
    visible = []
    for event in chunk:
        row = dict(event)
        row.pop("search_text", None)
        visible.append(row)
    return visible, next_cursor


def _rank_pages(pages, events, invoices) -> list[dict]:
    enabled_ids, enabled_names = _routing_lookup()
    grouped_events = {page["id"]: [] for page in pages}
    for event in events:
        grouped_events.setdefault(event["page_id"], []).append(event)
    grouped_orders = {page["id"]: [] for page in pages}
    claimed = {event["order_id"] for event in events if event.get("order_id")}
    invoice_by_id = {row.id: row for row in invoices}
    for event in events:
        invoice = invoice_by_id.get(event.get("order_id"))
        if invoice:
            grouped_orders.setdefault(event["page_id"], []).append(invoice)
    for invoice in invoices:
        if invoice.id in claimed:
            continue
        for page in pages:
            if _page_match(invoice, page):
                grouped_orders[page["id"]].append(invoice)
                break
    raw = []
    for page in pages:
        page_events = grouped_events.get(page["id"], [])
        page_orders = _unique_invoices(grouped_orders.get(page["id"], []))
        messages = len(page_events)
        orders = len(page_orders)
        returns = sum(1 for row in page_orders if _norm(row.status) in RETURN_STATUSES)
        sales = sum(int(row.total or 0) for row in page_orders if _norm(row.status) not in CANCELED_STATUSES)
        answered = [
            event["response_seconds"]
            for event in page_events
            if event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"} and event["response_seconds"] is not None
        ]
        avg_response = int(sum(answered) / len(answered)) if answered else None
        conversion = (orders / messages * 100.0) if messages else 0.0
        raw.append({
            "page": page,
            "messages": messages,
            "orders": orders,
            "returns": returns,
            "sales": sales,
            "avg_response": avg_response,
            "conversion": conversion,
        })
    max_orders = max((row["orders"] for row in raw), default=0)
    max_sales = max((row["sales"] for row in raw), default=0)
    ranked = []
    for row in raw:
        score = page_strength_score(
            orders=row["orders"],
            max_orders=max_orders,
            conversion_rate=row["conversion"],
            sales=row["sales"],
            max_sales=max_sales,
            avg_response_seconds=row["avg_response"],
            returns=row["returns"],
        )
        ranked.append({
            "id": row["page"]["id"],
            "name": row["page"]["name"],
            "avatar": row["page"]["avatar"],
            "initials": _initials(row["page"]["name"]),
            "connected": bool(row["page"].get("connected")),
            "routing_on": _page_routing_on(row["page"], enabled_ids, enabled_names),
            "score": score,
            "tone": score_tone(score),
            "messages": row["messages"],
            "orders": row["orders"],
            "conversion_label": format_percent(row["conversion"]) if row["messages"] else "—",
            "response_label": format_duration(row["avg_response"]),
            "sales_label": format_iqd(row["sales"], compact=True),
        })
    ranked.sort(key=lambda item: (item["score"], item["orders"], item["messages"]), reverse=True)
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def _page_routing_on(page: dict, enabled_ids: set[str], enabled_names: set[str]) -> bool:
    ext = str(page.get("external_page_id") or "")
    if ext and ext in enabled_ids:
        return True
    name = _norm(page.get("name"))
    return bool(name and name in enabled_names)


def _unique_invoices(rows):
    return list({row.id: row for row in rows}.values())


def _classify_live(state, now):
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


def _live_by_employee(now):
    found = {}
    try:
        from modules.facebook_routing.models import FacebookEmployeeRouting
        from modules.facebook_routing.schema import ensure_facebook_routing_schema

        ensure_facebook_routing_schema()
        rows = FacebookEmployeeRouting.query.all()
    except Exception:
        return found
    for row in rows:
        kind, label = _classify_live(row, now)
        seen = getattr(row, "last_seen_at", None)
        found[row.employee_id] = (kind, label, format_ago(seen, now) if kind == "offline" else "")
    return found


def _employee_rows(employees, invoices, events, now, sort, selected_page):
    live_map = _live_by_employee(now)
    by_employee = {employee.id: {"orders": [], "events": []} for employee in employees}
    for invoice in invoices:
        if invoice.employee_id in by_employee:
            by_employee[invoice.employee_id]["orders"].append(invoice)
    for event in events:
        if event.get("employee_id") in by_employee:
            by_employee[event["employee_id"]]["events"].append(event)
    rows = []
    for employee in employees:
        bucket = by_employee[employee.id]
        live, live_label, seen_label = live_map.get(employee.id, ("offline", "", ""))
        if not bucket["orders"] and not bucket["events"] and live == "offline":
            continue
        orders = bucket["orders"]
        returns = sum(1 for row in orders if _norm(row.status) in RETURN_STATUSES)
        sales = sum(int(row.total or 0) for row in orders if _norm(row.status) not in CANCELED_STATUSES)
        speeds = [
            event["response_seconds"]
            for event in bucket["events"]
            if event["status"] in {"ANSWERED", "ORDER_CREATED", "CLOSED"} and event["response_seconds"] is not None
        ]
        avg = int(sum(speeds) / len(speeds)) if speeds else None
        presence = "online" if live != "offline" else "offline"
        cap_row = _capacity_for(employee.id)
        rows.append({
            "id": employee.id,
            "name": employee.name,
            "avatar": ("/" + employee.profile_pic) if employee.profile_pic else "",
            "initials": _initials(employee.name),
            "presence": presence,
            "live": live,
            "live_label": live_label,
            "seen_label": seen_label,
            "orders": len(orders),
            "returns": returns,
            "sales": sales,
            "response_seconds": avg if avg is not None else 10**9,
            "response_label": format_duration(avg),
            "load": cap_row["load"],
            "cap": cap_row["cap"],
            "full": cap_row["full"],
        })
    if sort == "orders":
        rows.sort(key=lambda row: row["orders"], reverse=True)
    elif sort == "returns":
        rows.sort(key=lambda row: (row["returns"], -row["orders"]))
    elif sort == "speed":
        rows.sort(key=lambda row: row["response_seconds"])
    elif sort == "sales":
        rows.sort(key=lambda row: row["sales"], reverse=True)
    else:
        live_rank = {"typing": 0, "replying": 1, "open": 2, "offline": 3}
        rows.sort(key=lambda row: (live_rank.get(row.get("live"), 3), -row["orders"]))
    for row in rows:
        row.pop("response_seconds", None)
    return rows


def _normalize_act_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("act_"):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"act_{digits}" if digits else ""


def _ads_config(tenant_slug: str | None) -> dict:
    from sqlalchemy import text
    from extensions import db
    from modules.publisher.services.token_utils import decrypt_token

    tenant = tenant_slug or "default"
    try:
        db.session.execute(text(
            "CREATE TABLE IF NOT EXISTS facebook_monitor_ads ("
            "tenant_slug VARCHAR(100) PRIMARY KEY,"
            "ads_app_id VARCHAR(50),"
            "ads_app_secret TEXT,"
            "ads_user_token TEXT,"
            "ads_account_id VARCHAR(64))"
        ))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        row = db.session.execute(
            text(
                "SELECT ads_app_id, ads_app_secret, ads_user_token, ads_account_id "
                "FROM facebook_monitor_ads WHERE tenant_slug = :tenant"
            ),
            {"tenant": tenant},
        ).mappings().first()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {}
    if not row:
        return {}
    data = dict(row)
    token = data.get("ads_user_token") or ""
    if token:
        try:
            data["ads_user_token"] = decrypt_token(token) or token
        except Exception:
            pass
    data["ads_account_id"] = _normalize_act_id(data.get("ads_account_id"))
    return data


def _graph_active_ads(tenant_slug: str | None, start: datetime, end: datetime, *, allow_fetch: bool = True) -> tuple[list[dict], str]:
    import json
    import time
    import requests

    config = _ads_config(tenant_slug)
    token = (config.get("ads_user_token") or "").strip()
    act_id = config.get("ads_account_id") or ""
    if not token or not act_id:
        return [], ""

    cache_key = f"{tenant_slug or ''}|{act_id}|{start.date()}|{end.date()}"
    hit = _ADS_CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _ADS_CACHE_TTL:
        return list(hit[1]), hit[2]
    disk = _ads_disk_load()
    if not allow_fetch or _graph_cooling():
        if hit:
            return list(hit[1]), hit[2]
        if disk:
            return list(disk[0]), disk[1]
        return [], (_LIMIT_HINT if _graph_cooling() else "")

    since = start.date().isoformat()
    until = (end - timedelta(days=1)).date().isoformat()
    ads = []
    error = ""
    try:
        response = requests.get(
            f"{GRAPH_BASE}/{act_id}/ads",
            params={
                "access_token": token,
                "effective_status": '["ACTIVE"]',
                "fields": "id,name,effective_status,campaign{id,name},creative{thumbnail_url,image_url}",
                "limit": 40,
            },
            timeout=12,
        )
        payload = response.json()
        if payload.get("error"):
            err = payload.get("error") or {}
            if _is_limit_error(err):
                error = _mark_graph_limit()
            else:
                error = err.get("message") or "تعذر جلب الإعلانات من Marketing API."
            payload = {"data": []}
        for row in payload.get("data") or []:
            creative = row.get("creative") or {}
            campaign = row.get("campaign") or {}
            ads.append({
                "id": str(row.get("id") or ""),
                "name": row.get("name") or campaign.get("name") or "إعلان فيسبوك",
                "page_name": campaign.get("name") or "",
                "thumbnail": creative.get("thumbnail_url") or creative.get("image_url") or "",
                "active": True,
                "spend": None,
            })
        if not ads and not error:
            # Fallback: recent ads even if not ACTIVE, so the panel is not empty after connect.
            fallback = requests.get(
                f"{GRAPH_BASE}/{act_id}/ads",
                params={
                    "access_token": token,
                    "fields": "id,name,effective_status,campaign{id,name},creative{thumbnail_url,image_url}",
                    "limit": 20,
                },
                timeout=12,
            ).json()
            if fallback.get("error"):
                ferr = fallback.get("error") or {}
                error = _mark_graph_limit() if _is_limit_error(ferr) else (ferr.get("message") or error)
            for row in fallback.get("data") or []:
                creative = row.get("creative") or {}
                campaign = row.get("campaign") or {}
                status = str(row.get("effective_status") or "").upper()
                ads.append({
                    "id": str(row.get("id") or ""),
                    "name": row.get("name") or campaign.get("name") or "إعلان فيسبوك",
                    "page_name": campaign.get("name") or "",
                    "thumbnail": creative.get("thumbnail_url") or creative.get("image_url") or "",
                    "active": status == "ACTIVE",
                    "spend": None,
                })
    except Exception as exc:
        return [], str(exc)

    if error and not ads:
        _ADS_CACHE[cache_key] = (time.time(), [], error)
        return [], error
    if not ads:
        _ADS_CACHE[cache_key] = (time.time(), [], "")
        return [], ""
    if _graph_cooling():
        _ADS_CACHE[cache_key] = (time.time(), ads, error or _LIMIT_HINT)
        return ads, error or _LIMIT_HINT

    spend_by_id = {}
    messages_by_id = {}
    try:
        insights = requests.get(
            f"{GRAPH_BASE}/{act_id}/insights",
            params={
                "access_token": token,
                "level": "ad",
                "fields": "ad_id,ad_name,spend,actions",
                "time_range": json.dumps({"since": since, "until": until}),
                "limit": 200,
            },
            timeout=12,
        ).json()
        if not insights.get("error"):
            for row in insights.get("data") or []:
                ad_id = str(row.get("ad_id") or "")
                if not ad_id:
                    continue
                try:
                    spend_by_id[ad_id] = float(row.get("spend") or 0)
                except (TypeError, ValueError):
                    spend_by_id[ad_id] = 0.0
                messaging = 0
                for action in row.get("actions") or []:
                    action_type = str(action.get("action_type") or "")
                    if "messaging" not in action_type:
                        continue
                    try:
                        messaging = max(messaging, int(float(action.get("value") or 0)))
                    except (TypeError, ValueError):
                        continue
                if messaging:
                    messages_by_id[ad_id] = messaging
    except Exception:
        pass

    for ad in ads:
        if ad["id"] in spend_by_id:
            ad["spend"] = spend_by_id[ad["id"]]
        if ad["id"] in messages_by_id:
            ad["insights_messages"] = messages_by_id[ad["id"]]
    _ADS_CACHE[cache_key] = (time.time(), ads, "")
    _ads_disk_save(ads)
    return ads, ""


def _link_events_to_ads(events, marketing_ads: list[dict] | None) -> None:
    ads = marketing_ads or []
    by_id = {str(ad.get("id")): ad for ad in ads if ad.get("id")}
    by_name = {_norm(ad.get("name")): ad for ad in ads if ad.get("name")}
    for event in events:
        ad_id = str(event.get("ad_id") or "").strip()
        if ad_id and ad_id in by_id:
            if not event.get("campaign"):
                event["campaign"] = by_id[ad_id].get("name") or ""
            if event.get("source") == "Facebook Messenger":
                event["source"] = "إعلان فيسبوك"
            continue
        needle = _norm(event.get("campaign") or "")
        if needle and needle in by_name:
            matched = by_name[needle]
            event["ad_id"] = str(matched.get("id") or "")
            event["campaign"] = matched.get("name") or event.get("campaign") or ""
            event["source"] = "إعلان فيسبوك"


def _attribute_orders_to_ad_events(events, invoices) -> None:
    """Attach Finora orders to ad-sourced messenger events when confidence is high."""
    open_events = [event for event in events if event.get("ad_id") and not event.get("order_id")]
    if not open_events or not invoices:
        return
    used = {event.get("order_id") for event in events if event.get("order_id")}
    for event in open_events:
        received = None
        if event.get("received_at"):
            try:
                received = datetime.fromisoformat(str(event["received_at"]))
            except ValueError:
                received = None
        if not received:
            continue
        page_name = _norm(event.get("page_name"))
        customer = _norm(event.get("customer_name"))
        best = None
        for invoice in invoices:
            if invoice.id in used:
                continue
            if _norm(invoice.status) in CANCELED_STATUSES:
                continue
            if page_name and _norm(invoice.page_name) != page_name:
                continue
            if not invoice.created_at:
                continue
            delta = (invoice.created_at - received).total_seconds()
            if delta < -300 or delta > 6 * 3600:
                continue
            inv_customer = _norm(getattr(invoice, "customer_name", None) or "")
            if customer and inv_customer and customer not in inv_customer and inv_customer not in customer:
                continue
            score = abs(delta)
            if best is None or score < best[0]:
                best = (score, invoice)
        if not best:
            continue
        invoice = best[1]
        used.add(invoice.id)
        event["order_id"] = invoice.id
        event["order_label"] = f"ORD-{invoice.id}"
        event["order_total_label"] = format_iqd(invoice.total)
        event["attribution"] = "HIGH"
        event["employee_id"] = invoice.employee_id
        event["employee_name"] = invoice.employee_name or ""
        if event.get("status") in {"NEW", "WAITING_REPLY", "LATE", "ANSWERED"}:
            event["status"] = "ORDER_CREATED"
            event["status_label"] = STATUS_LABELS.get("ORDER_CREATED", "تحويل لطلب")


def _ad_rows(events, marketing_ads: list[dict] | None = None) -> list[dict]:
    grouped: dict[str, dict] = {}
    for ad in marketing_ads or []:
        if not ad.get("id"):
            continue
        grouped[ad["id"]] = {
            "id": ad["id"],
            "name": ad.get("name") or "إعلان فيسبوك",
            "page_name": ad.get("page_name") or "",
            "thumbnail": ad.get("thumbnail") or "",
            "active": bool(ad.get("active", True)),
            "event_messages": 0,
            "insights_messages": int(ad.get("insights_messages") or 0),
            "orders": 0,
            "order_ids": set(),
            "spend": ad.get("spend"),
        }
    for event in events:
        if not event.get("ad_id") and not event.get("campaign"):
            continue
        key = str(event.get("ad_id") or event.get("campaign"))
        bucket = grouped.setdefault(key, {
            "id": key,
            "name": event.get("campaign") or "إعلان فيسبوك",
            "page_name": event.get("page_name") or "",
            "thumbnail": "",
            "active": True,
            "event_messages": 0,
            "insights_messages": 0,
            "orders": 0,
            "order_ids": set(),
            "spend": None,
        })
        bucket["event_messages"] += 1
        if event.get("page_name") and not bucket["page_name"]:
            bucket["page_name"] = event["page_name"]
        if event.get("campaign") and bucket["name"] in {"", "إعلان فيسبوك"}:
            bucket["name"] = event["campaign"]
        if event.get("order_id") and event["order_id"] not in bucket["order_ids"]:
            bucket["order_ids"].add(event["order_id"])
            bucket["orders"] += 1
    rows = []
    for bucket in grouped.values():
        messages = max(int(bucket["event_messages"] or 0), int(bucket["insights_messages"] or 0))
        spend = bucket.get("spend")
        orders = bucket["orders"]
        rows.append({
            "id": bucket["id"],
            "name": bucket["name"],
            "page_name": bucket["page_name"],
            "thumbnail": bucket.get("thumbnail") or "",
            "active": bucket.get("active", True),
            "messages": messages,
            "orders": orders,
            "spend_label": format_usd(spend),
            "cost_per_message_label": format_usd((spend / messages) if spend is not None and messages else None),
            "cost_per_order_label": format_usd((spend / orders) if spend is not None and orders else None),
        })
    rows.sort(key=lambda row: (row["active"], row["messages"], row["orders"]), reverse=True)
    return rows


def _meta_banner(channels, now: datetime, graph_error: str = "") -> dict:
    last_sync = None
    degraded = False
    for channel in channels:
        if channel.last_webhook_at and (last_sync is None or channel.last_webhook_at > last_sync):
            last_sync = channel.last_webhook_at
        if channel.last_error and (not channel.last_webhook_at or now - channel.last_webhook_at > timedelta(minutes=30)):
            degraded = True
    message = _human_graph_error(graph_error or "")
    return {
        "degraded": bool(message),
        "message": message,
        "last_sync": last_sync.strftime("%I:%M %p") if last_sync else "",
    }
