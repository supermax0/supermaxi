"""Employee desk: reply to Facebook customers and book the order in one screen.

Booking reuses services.pos_checkout.create_pos_order so stock, treasury and
commissions follow the exact same rules as the POS.
"""
from __future__ import annotations

import json

from flask import Blueprint, g, jsonify, redirect, render_template, request, session

from extensions import db
from models.customer import Customer
from models.employee import Employee
from models.invoice import Invoice
from models.product import Product

employee_desk_bp = Blueprint(
    "employee_desk",
    __name__,
    template_folder="../../templates",
)

CITY_FALLBACK = "بغداد"


@employee_desk_bp.before_request
def _bind_tenant():
    if "user_id" not in session and not session.get("is_superadmin"):
        return None
    slug = session.get("tenant_slug")
    if slug:
        g.tenant = slug
    # This blueprint reads ai_sales_channel_account directly; make sure any
    # columns added to that model (e.g. the TikTok fields) exist before the
    # route queries it, instead of depending on ai_sales_bp having run first.
    from modules.ai_sales.schema import ensure_ai_sales_schema

    ensure_ai_sales_schema()
    return None


def _employee() -> Employee | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    employee = Employee.query.get(user_id)
    if not employee or not employee.is_active:
        return None
    return employee


def _viewer():
    """Desk is for employees. Admins may open it too."""
    if not session.get("user_id") and not session.get("is_superadmin"):
        return None, (jsonify({"ok": False, "error": "auth"}), 401)
    employee = _employee()
    if employee:
        if employee.role != "admin":
            from utils.permission_checks import employee_can

            if not employee_can(employee, "use_employee_desk"):
                return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        return {
            "id": employee.id,
            "name": employee.name,
            "role": employee.role or "",
            "avatar": ("/" + employee.profile_pic) if employee.profile_pic else "",
            "is_admin": (employee.role == "admin"),
        }, None
    if session.get("is_superadmin") or session.get("role") == "admin":
        return {
            "id": None,
            "name": session.get("user_name") or "المدير",
            "role": "admin",
            "avatar": "",
            "is_admin": True,
        }, None
    return None, (jsonify({"ok": False, "error": "forbidden"}), 403)


def _account_payload(employee: Employee | None, viewer: dict) -> dict:
    """Public profile for the phone account screen. Never includes the password."""
    role_labels = {"admin": "مدير", "cashier": "كاشير", "employee": "موظف"}
    pay_labels = {
        "none": "بدون راتب ثابت",
        "monthly": "راتب شهري",
        "weekly": "راتب أسبوعي",
        "commission": "عمولة فقط",
        "monthly_commission": "شهري مع عمولة",
        "weekly_commission": "أسبوعي مع عمولة",
    }
    perm_labels = (
        ("can_see_orders", "رؤية الطلبات"),
        ("can_see_orders_placed", "طلبات تم الطلب"),
        ("can_see_orders_delivered", "طلبات واصلة"),
        ("can_see_orders_returned", "طلبات راجعة"),
        ("can_see_orders_shipped", "طلبات مشحونة"),
        ("can_edit_price", "تعديل السعر"),
        ("can_see_reports", "التقارير"),
        ("can_manage_inventory", "المخزون"),
        ("can_see_expenses", "المصاريف"),
        ("can_manage_suppliers", "الموردين"),
        ("can_manage_customers", "الزبائن"),
        ("can_see_accounts", "الحسابات"),
        ("can_see_financial", "البيانات المالية"),
    )
    name = (viewer or {}).get("name") or "الحساب"
    if not employee:
        return {
            "name": name,
            "initial": (name[:1] or "م"),
            "avatar": "",
            "role_label": "مدير",
            "username": "",
            "employee_no": "",
            "active": True,
            "pay_title": "—",
            "pay_note": "حساب مدير",
            "salary": "—",
            "commission": "—",
            "orders": "—",
            "sales": "—",
            "details": [{"label": "نوع الحساب", "value": "مدير النظام", "copy": ""}],
            "perms": ["كل الصلاحيات"],
        }
    branch_name = ""
    shipping_name = ""
    try:
        from models.branch import Branch

        if employee.branch_id:
            branch = Branch.query.get(employee.branch_id)
            branch_name = (branch.name if branch else "") or ""
    except Exception:
        branch_name = ""
    try:
        from models.shipping import ShippingCompany

        if employee.shipping_company_id:
            company = ShippingCompany.query.get(employee.shipping_company_id)
            shipping_name = (company.name if company else "") or ""
    except Exception:
        shipping_name = ""
    role_key = (employee.role or "").strip().lower()
    role_names = []
    try:
        role_names = [str(row.name) for row in (employee.roles or []) if getattr(row, "name", None)]
    except Exception:
        role_names = []

    def _ar_role(raw: str) -> str:
        key = (raw or "").strip().lower()
        return role_labels.get(key, raw or "موظف")

    role_label = _ar_role(employee.role or "")
    if role_names:
        seen = []
        for raw in role_names:
            label = _ar_role(raw)
            if label and label not in seen:
                seen.append(label)
        if seen:
            role_label = "، ".join(seen)
    created = employee.created_at.strftime("%Y-%m-%d") if employee.created_at else "—"
    language = "العربية" if (employee.language or "ar") == "ar" else "English"
    pay_key = (employee.pay_type or "none").strip()
    pay_cards = {
        "none": ("بدون راتب", "لا يوجد راتب ثابت"),
        "monthly": ("شهري", "ثابت لكل دورة"),
        "weekly": ("أسبوعي", "ثابت لكل دورة"),
        "commission": ("عمولة فقط", "بدون راتب ثابت"),
        "monthly_commission": ("شهري", "+ عمولة"),
        "weekly_commission": ("أسبوعي", "+ عمولة"),
    }
    pay_title, pay_note = pay_cards.get(pay_key, (pay_labels.get(pay_key, pay_key or "—"), ""))

    def _detail(label, value, copy=False):
        text = (value or "").strip() or "—"
        return {"label": label, "value": text, "copy": text if copy and text != "—" else ""}

    if role_key == "admin":
        perms = ["كل الصلاحيات"]
    else:
        perms = [label for field, label in perm_labels if getattr(employee, field, False)]
    return {
        "name": employee.name or name,
        "initial": ((employee.name or name)[:1] or "م"),
        "avatar": ("/" + employee.profile_pic) if employee.profile_pic else "",
        "role_label": role_label,
        "username": employee.username or "",
        "employee_no": str(employee.id or ""),
        "active": bool(employee.is_active),
        "pay_title": pay_title,
        "pay_note": pay_note,
        "salary": _money(employee.salary),
        "commission": _money(employee.commission_percent),
        "orders": f"{int(employee.total_orders or 0):,}",
        "sales": _money(employee.total_sales),
        "details": [
            _detail("اسم المستخدم", employee.username, True),
            _detail("الهاتف", employee.phone, True),
            _detail("الفرع", branch_name),
            _detail("شركة التوصيل", shipping_name),
            _detail("رقم التحويل", employee.transfer_number, True),
            _detail("الحالة", "نشط" if employee.is_active else "موقوف"),
            _detail("اللغة", language),
            _detail("تاريخ فتح الحساب", created),
        ],
        "perms": perms,
    }


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _money(value) -> str:
    return f"{int(value or 0):,} د.ع".replace(",", ",")


# ── Page ──────────────────────────────────────────────────────────────────
@employee_desk_bp.get("/employee-desk")
def desk_page():
    viewer, error = _viewer()
    if error:
        slug = (session.get("tenant_slug") or "").strip()
        return redirect(f"/employee-desk/login/{slug}" if slug else "/employee-desk/login")
    return render_template(
        "employee_desk/app.html",
        viewer=viewer,
        account=_account_payload(_employee(), viewer),
    )


@employee_desk_bp.get("/employee-desk/training")
def training_page():
    viewer, error = _viewer()
    if error:
        return error
    response = render_template(
        "employee_desk/training.html",
        viewer=viewer,
        training_scope=f"{session.get('tenant_slug') or session.get('tenant_id') or 'core'}:{viewer['id'] or 'admin'}",
    )
    return response, 200, {"Cache-Control": "private, no-store"}


def _activate_tenant(slug: str):
    from models.core.tenant import Tenant as CoreTenant

    slug = (slug or "").strip().lower()
    if not slug:
        return None, "أدخل معرف الشركة"
    prev = getattr(g, "tenant", None)
    g.tenant = None
    try:
        core = CoreTenant.query.filter_by(slug=slug).first()
    finally:
        g.tenant = prev
    if not core:
        return None, "الشركة غير موجودة"
    if not core.is_active:
        return None, "اشتراك هذه الشركة موقف"
    g.tenant = core.slug
    return core, None


@employee_desk_bp.get("/employee-desk/login")
@employee_desk_bp.get("/employee-desk/login/<tenant_slug>")
def desk_login_page(tenant_slug=None):
    slug = (tenant_slug or session.get("tenant_slug") or "").strip().lower()
    viewer, error = _viewer()
    if viewer and not error:
        return redirect("/employee-desk")
    return render_template("employee_desk/login.html", tenant_slug=slug, error="")


@employee_desk_bp.post("/employee-desk/login")
@employee_desk_bp.post("/employee-desk/login/<tenant_slug>")
def desk_login(tenant_slug=None):
    from werkzeug.security import check_password_hash
    from utils.permission_checks import employee_can

    data = request.get_json(silent=True) or request.form or {}
    slug = str(data.get("tenant_slug") or tenant_slug or "").strip().lower()
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    if not slug or not username or not password:
        return jsonify({"ok": False, "error": "أدخل الشركة والمستخدم وكلمة المرور"}), 400
    core, err = _activate_tenant(slug)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    emp = None
    for candidate in Employee.query.filter(db.func.lower(Employee.username) == username.lower()).all():
        hashed = False
        try:
            hashed = check_password_hash(candidate.password, password)
        except Exception:
            hashed = False
        if hashed or candidate.password == password:
            emp = candidate
            break
    if not emp or not emp.is_active:
        return jsonify({"ok": False, "error": "بيانات الدخول غلط أو الحساب موقف"}), 401
    if emp.role != "admin" and not employee_can(emp, "use_employee_desk"):
        return jsonify({"ok": False, "error": "ما عندك صلاحية مكتب الموظف"}), 403
    session.clear()
    session.permanent = True
    session["tenant_slug"] = core.slug
    session["user_id"] = emp.id
    session["name"] = emp.name
    session["role"] = emp.role
    session["tenant_id"] = emp.tenant_id
    return jsonify({"ok": True, "redirect": "/employee-desk"})


@employee_desk_bp.get("/employee-desk/logout")
def desk_logout():
    slug = (session.get("tenant_slug") or "").strip()
    session.clear()
    return redirect(f"/employee-desk/login/{slug}" if slug else "/employee-desk/login")


@employee_desk_bp.get("/employee-desk/manifest.webmanifest")
def desk_manifest():
    return jsonify({
        "name": "مكتب الموظف",
        "short_name": "المكتب",
        "start_url": "/employee-desk",
        "scope": "/employee-desk",
        "display": "standalone",
        "dir": "rtl",
        "lang": "ar",
        "background_color": "#650016",
        "theme_color": "#650016",
        "icons": [{"src": "/static/logo.png", "sizes": "192x192", "type": "image/png"}],
    }), 200, {"Content-Type": "application/manifest+json"}


@employee_desk_bp.get("/employee-desk/sw.js")
def desk_sw():
    return (
        "self.addEventListener('install',(e)=>self.skipWaiting());"
        "self.addEventListener('activate',(e)=>e.waitUntil(self.clients.claim()));"
        "self.addEventListener('notificationclick',(e)=>{e.notification.close();"
        "e.waitUntil(self.clients.openWindow('/employee-desk'));});",
        200,
        {"Content-Type": "application/javascript", "Cache-Control": "no-store"},
    )


@employee_desk_bp.get("/api/employee-desk/alerts")
def desk_alerts():
    viewer, error = _viewer()
    if error:
        return error
    emp_id = viewer.get("id")
    if not emp_id:
        return jsonify({"ok": True, "unread": 0, "latest": None})
    from modules.ai_sales.models import AISalesConversation

    try:
        from modules.facebook_routing.engine import reassign_overdue

        reassign_overdue()
    except Exception:
        pass
    rows = (
        AISalesConversation.query.filter(
            AISalesConversation.assigned_employee_id == emp_id,
            AISalesConversation.status != "closed",
        )
        .order_by(AISalesConversation.last_customer_message_at.desc())
        .limit(60)
        .all()
    )
    owners = _latest_assignee_map(rows)
    waiting = []
    for row in rows:
        channel = row.channel
        page_id = str((channel.page_id if channel else "") or "")
        psid = str(row.external_contact_id or "")
        if not page_id or not psid or owners.get((page_id, psid)) != int(emp_id):
            continue
        last_c = row.last_customer_message_at
        last_b = row.last_business_message_at
        if last_c and (not last_b or last_c > last_b):
            waiting.append(row)
    latest = waiting[0] if waiting else None
    channel = latest.channel if latest else None
    preview = (latest.summary or "رسالة جديدة بانتظار ردك")[:140] if latest else ""
    if latest:
        from modules.ai_sales.models import AISalesMessage

        last = (
            AISalesMessage.query.filter_by(conversation_id=latest.id)
            .order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc())
            .first()
        )
        if last:
            preview = (last.text_content or last.transcription or "").strip() or preview
            if not preview:
                kind = (last.message_type or "").lower()
                preview = {"image": "صورة", "video": "فيديو", "audio": "صوت"}.get(kind, "رسالة جديدة بانتظار ردك")
    return jsonify({
        "ok": True,
        "unread": len(waiting),
        "latest": None if not latest else {
            "name": latest.contact_name or "زبون",
            "preview": preview[:140],
            "page": channel.name if channel else "",
            "psid": latest.external_contact_id or "",
            "page_id": (channel.page_id if channel else "") or "",
        },
    })


def _desk_time(moment, now) -> str:
    from datetime import timedelta

    if not moment:
        return ""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "الآن"
    if seconds < 3600:
        mins = max(1, seconds // 60)
        return f"قبل {mins} د"
    local = moment + timedelta(hours=3)
    if seconds < 86400:
        return local.strftime("%H:%M")
    if seconds < 86400 * 7:
        return f"قبل {seconds // 86400} يوم"
    return local.strftime("%m/%d")


def _latest_assignee_map(conversations) -> dict[tuple[str, str], int | None]:
    """Latest assignee for each Facebook customer, across duplicate threads."""
    from datetime import datetime

    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation
    from modules.facebook_routing.engine import FACEBOOK_CHANNELS

    psids = {str(row.external_contact_id or "") for row in conversations if row.external_contact_id}
    psids.discard("")
    if not psids:
        return {}
    channels = {
        row.id: str(row.page_id or "")
        for row in AISalesChannelAccount.query.filter(
            AISalesChannelAccount.channel_type.in_(tuple(FACEBOOK_CHANNELS))
        ).all()
    }
    found = {}
    siblings = AISalesConversation.query.filter(AISalesConversation.external_contact_id.in_(psids)).all()
    for convo in siblings:
        page_id = channels.get(convo.channel_account_id)
        if page_id is None:
            continue
        key = (page_id, str(convo.external_contact_id or ""))
        current = found.get(key)
        if current is None or (convo.updated_at or datetime.min) >= (current.updated_at or datetime.min):
            found[key] = convo
    return {
        key: int(row.assigned_employee_id) if row.assigned_employee_id else None
        for key, row in found.items()
    }


def _local_inbox(viewer) -> tuple[list[dict], dict]:
    from datetime import datetime, timedelta

    from modules.ai_sales.models import AISalesConversation, AISalesMessage
    from modules.facebook_monitor.status import LATE_SECONDS, STATUS_LABELS

    now = datetime.utcnow()
    emp_id = viewer.get("id")
    query = AISalesConversation.query
    if emp_id and not viewer.get("is_admin"):
        query = query.filter(AISalesConversation.assigned_employee_id == emp_id)
    elif emp_id:
        query = query.filter(
            db.or_(
                AISalesConversation.assigned_employee_id == emp_id,
                AISalesConversation.assigned_employee_id.is_(None),
            )
        )
    rows = query.order_by(AISalesConversation.updated_at.desc()).limit(160).all()
    owners = _latest_assignee_map(rows) if emp_id and not viewer.get("is_admin") else {}
    # Keep older unanswered threads for employees; don't bury them under recent answered chats.
    def _waiting(row):
        last_c = row.last_customer_message_at
        last_b = row.last_business_message_at
        if row.status == "closed":
            return False
        return bool(last_c and (not last_b or last_c > last_b))

    rows.sort(
        key=lambda row: (
            0 if _waiting(row) else 1,
            -(row.last_customer_message_at or row.updated_at or datetime.min).timestamp(),
        )
    )
    rows = rows[:80]
    ids = [row.id for row in rows]
    lasts = {}
    if ids:
        from sqlalchemy import func

        latest_ids = (
            db.session.query(func.max(AISalesMessage.id))
            .filter(AISalesMessage.conversation_id.in_(ids))
            .group_by(AISalesMessage.conversation_id)
        )
        for message in AISalesMessage.query.filter(AISalesMessage.id.in_(latest_ids)).all():
            lasts[message.conversation_id] = message

    counts = {"ALL": 0, "NEW": 0, "WAITING_REPLY": 0, "LATE": 0, "ANSWERED": 0, "ORDER_CREATED": 0, "CLOSED": 0}
    events = []
    seen = set()
    for row in rows:
        channel = row.channel
        page_id = str((channel.page_id if channel else "") or "")
        psid = str(row.external_contact_id or "")
        # A customer can have an old thread still tagged with this employee
        # while the live thread was moved or never assigned. Reply checks the
        # live thread, so the inbox must use that same assignee.
        if emp_id and not viewer.get("is_admin"):
            if not page_id or not psid or owners.get((page_id, psid)) != int(emp_id):
                continue
            if (page_id, psid) in seen:
                continue
            seen.add((page_id, psid))
        last = lasts.get(row.id)
        last_c = row.last_customer_message_at
        last_b = row.last_business_message_at
        waiting = bool(last_c and (not last_b or last_c > last_b))
        if not waiting and not last and not last_c and not last_b:
            waiting = True
        if row.status == "closed":
            status = "CLOSED"
        elif waiting and last_c and (now - last_c) >= timedelta(seconds=LATE_SECONDS):
            status = "LATE"
        elif waiting:
            status = "WAITING_REPLY"
        else:
            status = "ANSWERED"
        text = ""
        outbound = False
        if last:
            text = (last.text_content or last.transcription or "").strip()
            outbound = (last.direction or "") != "inbound"
            if not text:
                kind = (last.message_type or "").lower()
                text = {"image": "صورة", "video": "فيديو", "audio": "صوت"}.get(kind, "مرفق")
        if not text:
            text = (row.summary or "").strip() or "افتح المحادثة"
        preview = f"{'أنت' if outbound else 'العميل'}: {text}"
        name = row.contact_name or "زبون"
        stamp = (last.created_at if last else None) or last_c or last_b or row.updated_at
        events.append({
            "id": row.id,
            "thread_id": "",
            "external_page_id": page_id,
            "customer_psid": row.external_contact_id or "",
            "can_open": bool(page_id and row.external_contact_id),
            "ai_conversation_id": row.id,
            "page_id": f"fb:{page_id}" if page_id else "",
            "page_name": (channel.name if channel else "") or "فيسبوك",
            "page_avatar": "",
            "page_initials": (name[:1] or "ف"),
            "customer_name": name,
            "customer_avatar": "",
            "customer_initials": name[:1] or "ف",
            "preview": preview[:160],
            "received_at": stamp.isoformat() if stamp else "",
            "time_label": _desk_time(stamp, now),
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "response_tone": "danger" if status == "LATE" else ("warning" if waiting else "success"),
            "unread_count": 1 if waiting else 0,
            "assigned_employee_id": row.assigned_employee_id,
        })
        counts["ALL"] += 1
        if status in counts:
            counts[status] += 1
    return events, counts


_SNIPPET_TTL = 180
_snippet_cache: dict[str, tuple[float, dict]] = {}


def _graph_iso(value: str):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _wanted_page_ids(viewer) -> list[str]:
    emp_id = viewer.get("id")
    wanted: list[str] = []
    if emp_id:
        try:
            from modules.facebook_routing.models import FacebookPageEmployee

            wanted = [
                str(row.page_id)
                for row in FacebookPageEmployee.query.filter_by(employee_id=emp_id, is_enabled=True).all()
                if row.page_id
            ]
        except Exception:
            wanted = []
    if wanted:
        return wanted
    try:
        from modules.facebook_routing.models import FacebookPageRouting

        return [
            str(row.page_id)
            for row in FacebookPageRouting.query.filter_by(routing_enabled=True).all()
            if row.page_id
        ]
    except Exception:
        return []


def _graph_snippets(viewer) -> dict:
    import time

    import requests

    from modules.facebook_monitor.service import _graph_cooling, _is_limit_error, _mark_graph_limit
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token
    from utils.meta_graph import GRAPH_BASE

    cache_key = str(viewer.get("id") or "admin")
    cached = _snippet_cache.get(cache_key)
    if cached and cached[1] and (time.time() - cached[0]) < _SNIPPET_TTL:
        return cached[1]
    if _graph_cooling():
        return cached[1] if cached else {}
    wanted = set(_wanted_page_ids(viewer))
    rows = PublisherPage.query.filter(PublisherPage.page_token.isnot(None)).all()
    if wanted:
        rows = [row for row in rows if str(row.page_id) in wanted]
    else:
        return cached[1] if cached else {}
    found = {}
    for row in rows[:6]:
        token = decrypt_token(row.page_token or "")
        page_id = str(row.page_id or "")
        if not token or not page_id:
            continue
        try:
            payload = requests.get(
                f"{GRAPH_BASE}/{page_id}/conversations",
                params={
                    "platform": "messenger",
                    "access_token": token,
                    "limit": 40,
                    "fields": "snippet,unread_count,updated_time,participants{id,name}",
                },
                timeout=8,
            ).json()
        except Exception:
            continue
        err = payload.get("error") or {}
        if _is_limit_error(err):
            _mark_graph_limit()
            break
        if err:
            continue
        for thread in payload.get("data") or []:
            parts = ((thread.get("participants") or {}).get("data") or [])
            customer = next((part for part in parts if str(part.get("id") or "") != page_id), {})
            psid = str(customer.get("id") or "")
            if not psid:
                continue
            found[f"{page_id}:{psid}"] = {
                "page_id": page_id,
                "page_name": row.page_name or "فيسبوك",
                "psid": psid,
                "name": customer.get("name") or "زبون",
                "snippet": str(thread.get("snippet") or "").strip(),
                "unread": int(thread.get("unread_count") or 0),
                "updated": thread.get("updated_time") or "",
            }
    if found:
        _snippet_cache[cache_key] = (time.time(), found)
    return found or (cached[1] if cached else {})


def _persist_snippets(snippets: dict) -> None:
    if not snippets:
        return
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation

    dirty = False
    channels = {}
    for hit in snippets.values():
        page_id = hit["page_id"]
        if page_id not in channels:
            channels[page_id] = AISalesChannelAccount.query.filter_by(page_id=page_id).first()
        channel = channels[page_id]
        if not channel:
            continue
        row = AISalesConversation.query.filter_by(
            channel_account_id=channel.id,
            external_contact_id=hit["psid"],
        ).first()
        if not row:
            continue
        snippet = hit["snippet"][:300]
        if snippet and row.summary != snippet:
            row.summary = snippet
            dirty = True
        stamp = _graph_iso(hit.get("updated") or "")
        if stamp:
            if hit["unread"] and (not row.last_customer_message_at or row.last_customer_message_at < stamp):
                row.last_customer_message_at = stamp
                dirty = True
            if not row.updated_at or row.updated_at < stamp:
                row.updated_at = stamp
                dirty = True
    if dirty:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _apply_graph_snippets(events: list[dict], counts: dict, viewer) -> tuple[list[dict], dict]:
    from datetime import datetime

    snippets = _graph_snippets(viewer)
    if not snippets:
        return events, counts
    now = datetime.utcnow()
    known = {f"{row.get('external_page_id')}:{row.get('customer_psid')}" for row in events}
    for row in events:
        hit = snippets.get(f"{row.get('external_page_id')}:{row.get('customer_psid')}")
        if not hit:
            continue
        if hit["snippet"]:
            row["preview"] = hit["snippet"][:160]
        if hit["unread"]:
            row["unread_count"] = hit["unread"]
            if row.get("status") == "ANSWERED":
                row["status"] = "WAITING_REPLY"
                row["status_label"] = "بانتظار الرد"
                row["response_tone"] = "warning"
        stamp = _graph_iso(hit.get("updated") or "")
        if stamp:
            row["received_at"] = stamp.isoformat()
            row["time_label"] = _desk_time(stamp, now)
    for key, hit in snippets.items():
        if key in known:
            continue
        if not hit["snippet"] and not hit["unread"]:
            continue
        events.append({
            "id": f"g:{hit['page_id']}:{hit['psid']}",
            "thread_id": "",
            "external_page_id": hit["page_id"],
            "customer_psid": hit["psid"],
            "can_open": True,
            "page_name": hit["page_name"],
            "customer_name": hit["name"],
            "customer_avatar": "",
            "customer_initials": (hit["name"][:1] or "ف"),
            "page_initials": (hit["name"][:1] or "ف"),
            "preview": hit["snippet"][:160] or "رسالة جديدة",
            "received_at": (_graph_iso(hit.get("updated") or "") or datetime.utcnow()).isoformat(),
            "time_label": _desk_time(_graph_iso(hit.get("updated") or ""), datetime.utcnow()),
            "status": "WAITING_REPLY" if hit["unread"] else "ANSWERED",
            "status_label": "بانتظار الرد" if hit["unread"] else "تم الرد",
            "response_tone": "warning" if hit["unread"] else "success",
            "unread_count": hit["unread"] or (1 if hit["snippet"] else 0),
            "assigned_employee_id": viewer.get("id"),
        })
    counts = {"ALL": 0, "NEW": 0, "WAITING_REPLY": 0, "LATE": 0, "ANSWERED": 0, "ORDER_CREATED": 0, "CLOSED": 0}
    for row in events:
        counts["ALL"] += 1
        key = row.get("status") or ""
        if key in counts:
            counts[key] += 1
    events.sort(key=lambda row: (int(row.get("unread_count") or 0) > 0, row.get("received_at") or ""), reverse=True)
    try:
        _persist_snippets(snippets)
    except Exception:
        db.session.rollback()
    return events, counts


# ── Inbox: local first so the phone app stays light ───────────────────────
@employee_desk_bp.get("/api/employee-desk/inbox")
def inbox():
    viewer, error = _viewer()
    if error:
        return error
    if str(request.args.get("full") or "") != "1":
        messages, counts = _local_inbox(viewer)
        return jsonify({
            "ok": True,
            "fast": True,
            "messages": messages,
            "status_counts": counts,
            "next_cursor": "",
            "viewer": viewer,
        })

    from modules.facebook_monitor.service import build_snapshot
    from modules.publisher.services.schema_guard import ensure_publisher_schema

    args = request.args.to_dict(flat=True)
    args.setdefault("range", "last_30")
    try:
        try:
            ensure_publisher_schema(force=True)
        except Exception:
            db.session.rollback()
        payload = build_snapshot(
            args,
            tenant_id=_int(session.get("tenant_id")) or None,
            tenant_slug=session.get("tenant_slug"),
            skip_graph=True,
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500

    from modules.facebook_routing.engine import can_view_all

    messages = payload.get("messages") or []
    employee = _employee()
    if not can_view_all(employee, is_admin=bool(viewer.get("is_admin"))):
        mine = viewer.get("id")
        def _same_id(value):
            try:
                return int(value) == int(mine)
            except (TypeError, ValueError):
                return False
        messages = [row for row in messages if _same_id(row.get("assigned_employee_id"))]
        counts = {"ALL": 0, "NEW": 0, "WAITING_REPLY": 0, "LATE": 0, "ANSWERED": 0, "ORDER_CREATED": 0, "CLOSED": 0}
        for row in messages:
            counts["ALL"] += 1
            key = row.get("status") or ""
            if key in counts:
                counts[key] += 1
        payload["status_counts"] = counts

    return jsonify({
        "ok": True,
        "messages": messages,
        "status_counts": payload.get("status_counts") or {},
        "next_cursor": payload.get("next_cursor") or "",
        "meta": payload.get("meta") or {},
        "viewer": viewer,
    })


# ── Customers ─────────────────────────────────────────────────────────────
def _customer_payload(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name or "",
        "phone": customer.phone or "",
        "phone2": customer.phone2 or "",
        "city": customer.city or "",
        "address": customer.address or "",
        "blacklisted": bool(getattr(customer, "is_blacklisted", False)),
    }


@employee_desk_bp.get("/api/employee-desk/customers")
def search_customers():
    _, error = _viewer()
    if error:
        return error
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"ok": True, "customers": []})
    like = f"%{term}%"
    rows = (
        Customer.query.execution_options(skip_branch_scope=True)
        .filter(
            db.or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Customer.phone2.ilike(like),
            )
        )
        .order_by(Customer.id.desc())
        .limit(12)
        .all()
    )
    return jsonify({"ok": True, "customers": [_customer_payload(row) for row in rows]})


@employee_desk_bp.post("/api/employee-desk/customers")
def create_customer():
    _, error = _viewer()
    if error:
        return error
    from utils.customer_blacklist import is_phone_blacklisted_for_new_customer

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    phone2 = str(data.get("phone2") or "").strip()
    city = str(data.get("city") or "").strip() or CITY_FALLBACK
    address = str(data.get("address") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "أدخل اسم الزبون"}), 400
    if not phone:
        return jsonify({"ok": False, "error": "أدخل رقم الهاتف"}), 400
    if len(name) > 150 or len(phone) > 20 or len(phone2) > 20 or len(address) > 255:
        return jsonify({"ok": False, "error": "بيانات أطول من المسموح"}), 400

    try:
        existing = (
            Customer.query.execution_options(skip_branch_scope=True)
            .filter_by(phone=phone)
            .first()
        )
        if existing:
            if getattr(existing, "is_blacklisted", False):
                return jsonify({"ok": False, "error": "هذا الزبون في القائمة السوداء"}), 400
            # Fill gaps without overwriting verified data.
            existing.name = existing.name or name
            existing.city = existing.city or city
            existing.address = existing.address or (address or None)
            db.session.commit()
            return jsonify({"ok": True, "customer": _customer_payload(existing), "existing": True})

        if is_phone_blacklisted_for_new_customer(phone, phone2 or None):
            return jsonify({"ok": False, "error": "الرقم في القائمة السوداء"}), 400

        customer = Customer(
            name=name,
            phone=phone,
            phone2=phone2 or None,
            city=city,
            address=address or None,
            tenant_id=_int(session.get("tenant_id")) or None,
        )
        db.session.add(customer)
        db.session.commit()
        return jsonify({"ok": True, "customer": _customer_payload(customer), "existing": False})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500


@employee_desk_bp.get("/api/employee-desk/customers/<int:customer_id>/orders")
def customer_orders(customer_id: int):
    _, error = _viewer()
    if error:
        return error
    rows = (
        Invoice.query.execution_options(skip_branch_scope=True)
        .filter(Invoice.customer_id == customer_id, Invoice.deleted_at.is_(None))
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .limit(8)
        .all()
    )
    return jsonify({
        "ok": True,
        "orders": [
            {
                "id": row.id,
                "label": f"#{row.id}",
                "status": (row.status or "").strip(),
                "total_label": _money(row.total),
                "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else "",
            }
            for row in rows
        ],
    })


# ── Products ──────────────────────────────────────────────────────────────
@employee_desk_bp.get("/api/employee-desk/products")
@employee_desk_bp.get("/api/employee-desk/training/products")
def search_products():
    _, error = _viewer()
    if error:
        return error
    from utils.product_color_service import colors_for_product_dict

    employee = _employee()
    training = request.path == "/api/employee-desk/training/products"
    term = (request.args.get("q") or "").strip()
    query = Product.query.filter(
        Product.active.is_(True),
        Product.pos_visible.isnot(False),
    )
    if term:
        like = f"%{term}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.barcode.ilike(like),
            )
        )
    rows = query.order_by(Product.name.asc()).limit(48).all()

    out = []
    for product in rows:
        if employee is not None:
            try:
                from utils.trade_in_service import employee_can_access_replacement_product

                if not employee_can_access_replacement_product(employee, product):
                    continue
            except Exception:
                if training:
                    raise
        payload = {
            "id": product.id,
            "name": product.name,
            "sku": product.sku or "",
            "price": int(product.sale_price or 0),
            "price_label": _money(product.sale_price),
            "image_url": product.image_url or "",
        }
        if training:
            # Public selling facts only; never expose costs, margins or raw metadata.
            payload["description"] = product.description or ""
            from modules.storefront.services.product_presenter import product_specs

            try:
                meta = json.loads(product.meta_json or "{}")
            except (TypeError, ValueError):
                meta = {}
            payload["specs"] = product_specs(meta if isinstance(meta, dict) else {})
        try:
            payload.update(colors_for_product_dict(product))
        except Exception:
            payload["colors"] = []
        if training:
            # The shared POS color helper includes purchase prices. The academy
            # has its own explicit allowlist, including inside nested color rows.
            payload["colors"] = [
                {key: color[key] for key in ("name", "sale_price", "governorate_sale_price") if key in color}
                for color in payload.get("colors", []) if isinstance(color, dict)
            ]
            allowed = {"id", "name", "sku", "price", "price_label", "image_url", "description", "specs", "colors",
                       "dual_region_pricing", "governorate_sale_price", "primary_province"}
            payload = {key: value for key, value in payload.items() if key in allowed}
        out.append(payload)
    response = jsonify({"ok": True, "products": out})
    if training:
        response.headers["Cache-Control"] = "private, no-store"
    return response


# ── Booking ───────────────────────────────────────────────────────────────
@employee_desk_bp.post("/api/employee-desk/book")
def book_order():
    _, error = _viewer()
    if error:
        return error
    employee = _employee()
    if employee is None:
        return jsonify({"ok": False, "error": "الحجز متاح لحساب موظف فقط"}), 403

    from services.pos_checkout import PosCheckoutError, create_pos_order

    data = request.get_json(silent=True) or {}
    customer_id = _int(data.get("customer_id"))
    raw_items = data.get("items") or []
    if customer_id <= 0:
        return jsonify({"ok": False, "error": "اختر الزبون أولاً"}), 400

    items = []
    for row in raw_items:
        product_id = _int(row.get("product_id"))
        qty = max(1, _int(row.get("qty"), 1))
        if product_id <= 0:
            continue
        item = {"product_id": product_id, "qty": qty}
        color = str(row.get("color") or "").strip()
        if color:
            item["color"] = color
        items.append(item)
    if not items:
        return jsonify({"ok": False, "error": "أضف منتج واحد على الأقل"}), 400

    note = str(data.get("note") or "").strip() or None
    facebook_page_id = str(data.get("facebook_page_id") or "").strip()
    facebook_page_name = str(data.get("facebook_page_name") or "").strip()
    customer_psid = str(data.get("customer_psid") or "").strip()
    sales_page = None
    thread = {}
    try:
        from modules.employee_desk.page_link import attach_thread_to_invoice, resolve_sales_page, snapshot_thread

        sales_page = resolve_sales_page(
            facebook_page_id=facebook_page_id,
            facebook_page_name=facebook_page_name,
            employee=employee,
        )
        if facebook_page_id or customer_psid:
            thread = snapshot_thread(
                facebook_page_id=facebook_page_id,
                customer_psid=customer_psid,
                customer_name="",
                page_name=(sales_page.name if sales_page else facebook_page_name),
            )
            customer = Customer.query.get(customer_id)
            if customer:
                thread["customer_name"] = customer.name or thread.get("customer_name") or ""
    except Exception:
        sales_page = None
        thread = {}

    try:
        result = create_pos_order(
            employee=employee,
            customer_id=customer_id,
            items=items,
            note=note,
            page_id=sales_page.id if sales_page else None,
            submission_token=str(data.get("submission_token") or "") or None,
            source="employee_desk",
            raw_data=data,
        )
    except PosCheckoutError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc), "code": getattr(exc, "code", "")}), getattr(exc, "status", 400)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500

    invoice_id = result.get("invoice_id") or result.get("order_id")
    if invoice_id and thread:
        try:
            from modules.employee_desk.page_link import attach_thread_to_invoice

            invoice = Invoice.query.get(invoice_id)
            attach_thread_to_invoice(invoice, thread, customer_id)
            db.session.commit()
        except Exception:
            db.session.rollback()
    return jsonify({
        "ok": True,
        "order_id": invoice_id,
        "label": f"#{invoice_id}",
        "total_label": _money(result.get("total")),
        "stock_locked": bool(result.get("stock_locked")),
        "stock_lock_reason": result.get("stock_lock_reason") or "",
        "duplicate": bool(result.get("duplicate")),
        "page_name": (sales_page.name if sales_page else "") or "",
    })


# ── Quick replies ─────────────────────────────────────────────────────────
def _ensure_quick_replies():
    from modules.employee_desk.models import EmployeeQuickReply
    from sqlalchemy import inspect

    bind = db.session.get_bind()
    if bind is None:
        return
    tables = inspect(bind).get_table_names()
    if "employee_quick_reply" not in tables:
        EmployeeQuickReply.__table__.create(bind=bind, checkfirst=True)


def _quick_payload(row) -> dict:
    return {
        "id": row.id,
        "text": row.text or "",
        "mine": bool(row.employee_id and row.employee_id == session.get("user_id")),
    }


@employee_desk_bp.get("/api/employee-desk/quick-replies")
def list_quick_replies():
    _, error = _viewer()
    if error:
        return error
    from modules.employee_desk.models import EmployeeQuickReply

    try:
        _ensure_quick_replies()
        rows = (
            EmployeeQuickReply.query
            .order_by(EmployeeQuickReply.id.desc())
            .limit(40)
            .all()
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "replies": [_quick_payload(row) for row in rows]})


@employee_desk_bp.post("/api/employee-desk/quick-replies")
def create_quick_reply():
    viewer, error = _viewer()
    if error:
        return error
    from modules.employee_desk.models import EmployeeQuickReply

    data = request.get_json(silent=True) or {}
    text = " ".join(str(data.get("text") or "").split())
    if len(text) < 2:
        return jsonify({"ok": False, "error": "اكتب الرد أولاً"}), 400
    if len(text) > 280:
        return jsonify({"ok": False, "error": "الرد أطول من المسموح"}), 400
    try:
        _ensure_quick_replies()
        existing = EmployeeQuickReply.query.filter_by(text=text).first()
        if existing:
            return jsonify({"ok": True, "reply": _quick_payload(existing), "existing": True})
        if EmployeeQuickReply.query.count() >= 40:
            return jsonify({"ok": False, "error": "وصلت الحد الأقصى للردود"}), 400
        row = EmployeeQuickReply(employee_id=viewer.get("id"), text=text)
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "reply": _quick_payload(row)})


@employee_desk_bp.delete("/api/employee-desk/quick-replies/<int:reply_id>")
def delete_quick_reply(reply_id: int):
    _, error = _viewer()
    if error:
        return error
    from modules.employee_desk.models import EmployeeQuickReply

    try:
        _ensure_quick_replies()
        row = EmployeeQuickReply.query.get(reply_id)
        if not row:
            return jsonify({"ok": False, "error": "الرد غير موجود"}), 404
        db.session.delete(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True})
