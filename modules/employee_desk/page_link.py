"""Map a Facebook conversation onto a sales Page and snapshot the thread."""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.sql import func

from extensions import db
from models.page import Page


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def ensure_desk_link_schema() -> None:
    from flask import g

    engine = None
    slug = getattr(g, "tenant", None)
    if slug:
        try:
            from extensions_tenant import get_tenant_engine

            engine = get_tenant_engine(slug)
        except Exception:
            engine = None
    if engine is None:
        bind = db.session.get_bind()
        engine = bind if bind is not None else db.engine
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    stmts: list[str] = []
    if "page" in tables:
        cols = {col["name"] for col in inspector.get_columns("page")}
        if "facebook_page_id" not in cols:
            stmts.append("ALTER TABLE page ADD COLUMN facebook_page_id VARCHAR(128)")
    if "invoice" in tables:
        cols = {col["name"] for col in inspector.get_columns("invoice")}
        if "facebook_thread_json" not in cols:
            stmts.append("ALTER TABLE invoice ADD COLUMN facebook_thread_json TEXT")
    if not stmts:
        return
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def _facebook_page_name(facebook_page_id: str, fallback: str) -> str:
    name = " ".join(str(fallback or "").split())
    if name:
        return name[:150]
    if facebook_page_id:
        try:
            from modules.publisher.models.publisher_page import PublisherPage

            row = PublisherPage.query.filter_by(page_id=facebook_page_id).first()
            if row and row.page_name:
                return str(row.page_name).strip()[:150]
        except Exception:
            pass
        try:
            from modules.ai_sales.models import AISalesChannelAccount

            channel = AISalesChannelAccount.query.filter(
                AISalesChannelAccount.page_id == facebook_page_id,
                AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
            ).first()
            if channel and channel.name:
                return str(channel.name).strip()[:150]
        except Exception:
            pass
    return facebook_page_id or "فيسبوك"


def resolve_sales_page(*, facebook_page_id: str, facebook_page_name: str, employee) -> Page | None:
    """Find or create the CRM page for this Facebook page, and attach the employee."""
    ensure_desk_link_schema()
    fb_id = _digits(facebook_page_id)
    name = _facebook_page_name(fb_id, facebook_page_name)
    if not fb_id and not name:
        return None

    page = None
    if fb_id:
        page = Page.query.filter_by(facebook_page_id=fb_id).first()
    if page is None and name:
        page = Page.query.filter(func.lower(Page.name) == name.lower()).first()
    if page is None:
        page = Page(
            name=name,
            facebook_page_id=fb_id or None,
            visible_to_cashier=True,
            visible_to_admin=True,
        )
        db.session.add(page)
        db.session.flush()
    else:
        if fb_id and not getattr(page, "facebook_page_id", None):
            page.facebook_page_id = fb_id
        if name and page.name != name and not getattr(page, "facebook_page_id", None):
            page.name = name

    if employee is not None:
        try:
            assigned = page.employees.filter_by(id=employee.id).first()
        except Exception:
            assigned = employee if employee in page.employees.all() else None
        if assigned is None:
            page.employees.append(employee)
    db.session.flush()
    return page


def snapshot_thread(*, facebook_page_id: str, customer_psid: str, customer_name: str, page_name: str) -> dict:
    from modules.ai_sales.models import AISalesMessage
    from modules.facebook_routing.engine import conversation_for_psid

    fb_id = _digits(facebook_page_id)
    psid = _digits(customer_psid)
    conversation = conversation_for_psid(fb_id, psid) if fb_id and psid else None
    messages = []
    if conversation is not None:
        rows = (
            AISalesMessage.query.filter_by(conversation_id=conversation.id)
            .order_by(AISalesMessage.created_at.asc())
            .limit(80)
            .all()
        )
        for row in rows:
            text = (row.text_content or row.transcription or "").strip()
            if not text:
                kind = (row.message_type or "file").strip()
                text = {"image": "[صورة]", "video": "[فيديو]", "audio": "[صوت]"}.get(kind, "[مرفق]")
            who = "العميل" if (row.direction or "") == "inbound" else "الموظف"
            stamp = row.created_at or row.sent_at
            messages.append({
                "at": stamp.strftime("%Y-%m-%d %H:%M") if stamp else "",
                "from": who,
                "text": text[:800],
            })
    return {
        "facebook_page_id": fb_id,
        "page_name": page_name or "",
        "customer_psid": psid,
        "customer_name": customer_name or "",
        "conversation_id": conversation.id if conversation else None,
        "saved_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "messages": messages,
    }


def attach_thread_to_invoice(invoice, thread: dict, customer_id: int) -> None:
    if invoice is None or not thread:
        return
    invoice.facebook_thread_json = json.dumps(thread, ensure_ascii=False)
    invoice.source_module = "employee_desk"
    conv_id = thread.get("conversation_id")
    if not conv_id:
        return
    from modules.ai_sales.models import AISalesConversation

    conversation = AISalesConversation.query.get(int(conv_id))
    if conversation is None:
        return
    if customer_id and not conversation.customer_id:
        conversation.customer_id = customer_id
    context = conversation.get_context()
    context["created_order_id"] = invoice.id
    bookings = list(context.get("desk_bookings") or [])
    bookings.append({"invoice_id": invoice.id, "at": thread.get("saved_at")})
    context["desk_bookings"] = bookings[-20:]
    conversation.set_context(context)


def load_thread(invoice) -> dict | None:
    raw = getattr(invoice, "facebook_thread_json", None) if invoice else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    return {
        "page_name": data.get("page_name") or "",
        "customer_name": data.get("customer_name") or "",
        "saved_at": data.get("saved_at") or "",
        "messages": [
            {
                "at": str(row.get("at") or ""),
                "from": str(row.get("from") or ""),
                "text": str(row.get("text") or ""),
            }
            for row in messages
            if isinstance(row, dict)
        ],
    }
