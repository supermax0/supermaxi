# routes/delivery_agent.py
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, g
from extensions import db
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.order_item import OrderItem
from models.shipping_report import ShippingReport
from models.employee import Employee
from sqlalchemy import or_, and_, func
from datetime import datetime
import json
from urllib.parse import urlencode, urlsplit
from utils.business_time import business_date, business_datetime

from utils.agent_report_helpers import (
    STATUS_TO_AR,
    extract_agent_id_from_report,
    find_open_agent_report_for_order,
    find_open_agent_reports_for_order,
    get_order_applied_status,
    get_report_order_ids,
    get_report_progress,
    is_agent_report,
    notify_agent_report_ready,
    save_selection_to_report,
)
from utils.agent_employee_link import (
    bind_agent_messaging_session,
    clear_agent_messaging_session,
    ensure_agent_employee,
)
from utils.shipping_report_execute import execute_shipping_report
from utils.team_schema import ensure_delivery_agent_schema
from utils.invoice_schema_guard import ensure_invoice_schema

delivery_agent_bp = Blueprint("delivery_agent", __name__, url_prefix="/delivery-agent")

_AGENT_PENDING_STATUSES = ("تم الطلب", "جاري الشحن", "قيد الشحن")


def _normalize_tenant_slug(raw):
    return (raw or "").strip().lower()


def _resolve_request_tenant_slug():
    view_args = request.view_args or {}
    if view_args.get("tenant_slug"):
        return _normalize_tenant_slug(view_args["tenant_slug"])
    if request.args.get("tenant"):
        return _normalize_tenant_slug(request.args.get("tenant"))
    if request.method == "POST":
        data = request.get_json(silent=True) if request.is_json else None
        if isinstance(data, dict) and data.get("tenant_slug"):
            return _normalize_tenant_slug(data.get("tenant_slug"))
        if request.form.get("tenant_slug"):
            return _normalize_tenant_slug(request.form.get("tenant_slug"))
    if session.get("agent_tenant_slug"):
        return _normalize_tenant_slug(session.get("agent_tenant_slug"))
    return None


def _activate_tenant_slug(slug):
    from models.core.tenant import Tenant as CoreTenant

    if not slug:
        return None, "يرجى إدخال معرف الشركة"
    prev = getattr(g, "tenant", None)
    g.tenant = None
    try:
        core_tenant = CoreTenant.query.filter(db.func.lower(CoreTenant.slug) == slug).first()
    finally:
        if not getattr(g, "tenant", None):
            g.tenant = prev
    if not core_tenant:
        return None, "الشركة غير موجودة. تأكد من معرف الشركة."
    if not core_tenant.is_active:
        return None, "اشتراك هذه الشركة غير مفعّل أو تم إيقافه."
    g.tenant = core_tenant.slug
    return core_tenant, None


@delivery_agent_bp.before_request
def _bind_delivery_agent_tenant():
    ensure_delivery_agent_schema()
    ensure_invoice_schema()
    from utils.agent_tracking import ensure_agent_location_schema

    ensure_agent_location_schema()
    slug = _resolve_request_tenant_slug()
    if slug:
        _activate_tenant_slug(slug)
    elif session.get("agent_tenant_slug"):
        g.tenant = session.get("agent_tenant_slug")


@delivery_agent_bp.before_request
def _ensure_agent_messaging_session():
    if "agent_id" not in session:
        return None
    agent = DeliveryAgent.query.get(session["agent_id"])
    tenant_slug = session.get("agent_tenant_slug")
    if not agent or not tenant_slug:
        return None
    bind_agent_messaging_session(session, agent, tenant_slug)
    return None


_AR_MONTHS = (
    "",
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
)


def _arabic_date_label(raw):
    """تاريخ عرض فقط، مثل 30 سبتمبر 2026. لا يغيّر القيمة المخزّنة."""
    text = (raw or "").strip()
    if len(text) < 10:
        return text
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except Exception:
        return text
    return f"{parsed.day} {_AR_MONTHS[parsed.month]} {parsed.year}"


def _ready_manifests(orders):
    groups = {}
    for order in orders:
        report_id = order.get("report_id")
        if not report_id:
            continue
        groups.setdefault(report_id, []).append(order)
    ready = []
    for report_id, group in groups.items():
        if group and all(item.get("applied_status") for item in group):
            ready.append({
                "report_id": report_id,
                "report_number": group[0].get("report_number") or "",
            })
    return ready


def _agent_login_redirect(tenant_slug=None):
    if tenant_slug:
        return url_for("delivery_agent.login_page_tenant", tenant_slug=tenant_slug)
    return url_for("delivery_agent.login_page")


def _agent_pending_orders(agent_id):
    """طلبات المندوب فقط — بدون ربط بكشف شركة الشحن."""
    rows = (
        Invoice.query.filter(
            Invoice.delivery_agent_id == agent_id,
            Invoice.status.in_(_AGENT_PENDING_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
        .all()
    )
    return [_serialize_agent_order(o) for o in rows]


def _agent_active_report_orders(agent_id):
    """طلبات المندوب مجمعة حسب كشوفه المفتوحة، مع إبقاء الطلبات المباشرة ظاهرة."""
    reports = (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(False),
            ShippingReport.report_number.like(f"AGT-{int(agent_id)}-%"),
        )
        .order_by(ShippingReport.created_at.desc(), ShippingReport.id.desc())
        .all()
    )

    grouped_orders = []
    report_order_ids = set()

    for report in reports:
        order_ids = get_report_order_ids(report)
        if not order_ids:
            continue

        invoices = {
            order.id: order
            for order in Invoice.query.filter(Invoice.id.in_(order_ids)).all()
        }
        try:
            selections = json.loads(report.order_status_selections or "{}")
        except Exception:
            selections = {}

        report_orders = []
        for order_id in order_ids:
            order = invoices.get(order_id)
            if not order:
                continue
            serialized = _serialize_agent_order(order)
            selected = selections.get(str(order_id))
            if selected:
                serialized["applied_status"] = STATUS_TO_AR.get(selected, selected)
                serialized["pending_accountant"] = True
            report_orders.append(serialized)
            report_order_ids.add(order_id)

        if not report_orders:
            continue

        report_total = sum(int(order.get("remaining", 0) or 0) for order in report_orders)
        created_raw = report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else ""
        report_meta = {
            "report_id": report.id,
            "report_number": report.report_number,
            "report_created_at": created_raw,
            "report_date_label": _arabic_date_label(created_raw),
            "report_orders_count": len(report_orders),
            "report_total_amount": report_total,
        }
        for order in report_orders:
            order.update(report_meta)
        grouped_orders.extend(report_orders)

    # لا نخفي الطلبات التي ربطت بالمندوب مباشرة ولم تدخل في كشف بعد.
    direct_orders = [
        order for order in _agent_pending_orders(agent_id)
        if order["id"] not in report_order_ids
    ]
    if direct_orders:
        direct_meta = {
            "report_id": None,
            "report_number": "طلبات مرتبطة مباشرة",
            "report_created_at": "",
            "report_date_label": "",
            "report_orders_count": len(direct_orders),
            "report_total_amount": sum(int(order.get("remaining", 0) or 0) for order in direct_orders),
        }
        for order in direct_orders:
            order.update(direct_meta)
        grouped_orders.extend(direct_orders)

    return grouped_orders


def _agent_open_report_for_order(agent_id, order_id, report_id=None):
    """أعد كشفاً مفتوحاً يملكه المندوب ويحتوي الطلب، بما يشمل الكشوف القديمة."""
    if report_id:
        report = ShippingReport.query.get(report_id)
        reports = [report] if report else []
    else:
        reports = find_open_agent_reports_for_order(int(order_id), int(agent_id))

    for report in reports:
        if not report or report.is_executed or not is_agent_report(report):
            continue
        if extract_agent_id_from_report(report.report_number) != int(agent_id):
            continue
        if int(order_id) not in get_report_order_ids(report):
            continue
        return report
    return None


def _report_rows(report):
    try:
        rows = json.loads(report.orders_data or "[]")
    except (ValueError, TypeError):
        return []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _recorded_time(raw):
    if not raw:
        return None
    try:
        return business_datetime(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def _agent_delivery_summary(agent_id):
    from utils.agent_report_helpers import row_collectible_amount, DELIVERED_STATUSES

    today = business_date(datetime.utcnow())
    summary = {"delivered_total": 0, "delivered_count": 0, "awaiting_total": 0, "undated_count": 0}
    reports = ShippingReport.query.filter(
        ShippingReport.report_number.like(f"AGT-{int(agent_id)}-%"),
    ).all()
    seen = set()
    for report in reports:
        try:
            selections = json.loads(report.order_status_selections or "{}")
        except (ValueError, TypeError):
            selections = {}
        if not isinstance(selections, dict):
            continue
        for row in _report_rows(report):
            oid = str(row.get("id") or row.get("order_id"))
            if selections.get(oid) not in DELIVERED_STATUSES:
                continue
            amount = row_collectible_amount(row)
            if not report.is_executed:
                summary["awaiting_total"] += amount
            recorded = _recorded_time(row.get("agent_status_updated_at") or row.get("executed_at"))
            if not recorded:
                summary["undated_count"] += 1
            elif recorded.date() == today and oid not in seen:
                seen.add(oid)
                summary["delivered_total"] += amount
                summary["delivered_count"] += 1
    return summary


def _agent_delivered_today_total(agent_id):
    return _agent_delivery_summary(agent_id)["delivered_total"]


def _agent_order_stats(agent_id, active_orders=None):
    summary = _agent_delivery_summary(agent_id)
    if active_orders is not None:
        return {
            "pending_count": len(active_orders),
            "pending_total": sum(int(order.get("remaining", 0) or 0) for order in active_orders),
            **summary,
        }

    base = Invoice.query.filter(Invoice.delivery_agent_id == agent_id)
    pending_q = base.filter(Invoice.status.in_(_AGENT_PENDING_STATUSES))
    pending_orders = pending_q.all()
    pending_count = len(pending_orders)
    from utils.agent_report_helpers import order_payment_snapshot

    pending_total = sum(order_payment_snapshot(o)["remaining"] for o in pending_orders)
    return {
        "pending_count": int(pending_count),
        "pending_total": int(pending_total),
        **summary,
    }


def _agent_map_url(order):
    raw = (getattr(order, "location_url", None) or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw
    lat, lng = getattr(order, "location_lat", None), getattr(order, "location_lng", None)
    customer = getattr(order, "customer", None)
    query = f"{lat},{lng}" if lat is not None and lng is not None else " ".join(
        part for part in [getattr(customer, "city", ""), getattr(customer, "address", "")] if part
    )
    return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": query}) if query else ""


def _serialize_agent_order(order):
    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    applied_status = get_order_applied_status(order.id)
    from utils.agent_report_helpers import order_payment_snapshot

    payment = order_payment_snapshot(order)
    agent_note = (getattr(order, "agent_note", None) or "").strip()
    return {
        "id": order.id,
        "customer_name": order.customer_name,
        "phone": order.customer.phone if order.customer else "",
        "city": order.customer.city if order.customer else "",
        "address": order.customer.address if order.customer else "",
        "total": payment["total"],
        "paid_amount": payment["paid_amount"],
        "remaining": payment["remaining"],
        "status": order.status,
        "payment_status": order.payment_status,
        "items_count": len(items),
        "items": [{"name": item.product_name, "quantity": item.quantity,
                   "color": getattr(item, "variant_color", None) or ""} for item in items],
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
        "note": order.note or "",
        "agent_note": agent_note,
        "scheduled_date": order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else None,
        "applied_status": applied_status,
        "pending_accountant": bool(applied_status),
        "location_lat": getattr(order, "location_lat", None),
        "location_lng": getattr(order, "location_lng", None),
        "location_url": getattr(order, "location_url", None) or "",
        "location_label": getattr(order, "location_label", None) or "",
        "map_url": _agent_map_url(order),
    }


def _sync_agent_note_to_open_report(order_id: int, agent_note: str, report=None) -> None:
    """احفظ ملاحظة المندوب أيضاً داخل صف الكشف المفتوح إن وُجد."""
    report = report or find_open_agent_report_for_order(int(order_id))
    if not report or report.is_executed:
        return
    try:
        rows = json.loads(report.orders_data or "[]")
    except Exception:
        rows = []
    if not isinstance(rows, list):
        return
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = row.get("id") or row.get("order_id")
        try:
            if int(oid) != int(order_id):
                continue
        except (TypeError, ValueError):
            continue
        row["agent_note"] = agent_note
        changed = True
        break
    if changed:
        report.orders_data = json.dumps(rows, ensure_ascii=False)


def _build_executed_report_meta(agent_id):
    """order_id -> {final_status, executed_at, report_number} من كشوف AGT المنفّذة."""
    reports = (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(True),
            ShippingReport.report_number.like(f"AGT-{agent_id}-%"),
        )
        .order_by(ShippingReport.created_at.desc())
        .all()
    )
    meta = {}
    for report in reports:
        try:
            selections = json.loads(report.order_status_selections or "{}")
        except Exception:
            selections = {}
        execution_times = [_recorded_time(row.get("executed_at")) for row in _report_rows(report)]
        execution_times = [value for value in execution_times if value]
        exec_at = max(execution_times).strftime("%Y-%m-%d %H:%M") if execution_times else ""
        for oid in get_report_order_ids(report):
            if oid in meta:
                continue
            raw = selections.get(str(oid))
            final_status = STATUS_TO_AR.get(raw, raw) if raw else None
            meta[oid] = {
                "final_status": final_status,
                "executed_at": exec_at,
                "report_number": report.report_number,
            }
    return meta


def _serialize_completed_order(order, meta):
    base = _serialize_agent_order(order)
    base.update({
        "final_status": meta.get("final_status") or order.status,
        "invoice_status": order.status,
        "executed_at": meta.get("executed_at") or "",
        "executed_label": _arabic_date_label(meta["executed_at"]) if meta.get("executed_at") else "غير مسجل — كشف قديم",
        "report_number": meta.get("report_number") or "—",
    })
    return base


def _agent_completed_orders(agent_id, limit=100):
    """طلبات خرجت من قائمة العمل — حالات نهائية أو وردت في كشف AGT منفّذ."""
    report_meta = _build_executed_report_meta(agent_id)

    non_pending = (
        Invoice.query.filter(
            Invoice.delivery_agent_id == agent_id,
            ~Invoice.status.in_(_AGENT_PENDING_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
        .all()
    )

    order_map = {o.id: o for o in non_pending}

    for oid in report_meta:
        if oid in order_map:
            continue
        inv = Invoice.query.get(oid)
        if inv and inv.delivery_agent_id == agent_id:
            order_map[oid] = inv

    def sort_key(order):
        m = report_meta.get(order.id, {})
        return m.get("executed_at") or (
            order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else ""
        )

    orders = sorted(order_map.values(), key=sort_key, reverse=True)[:limit]
    return [_serialize_completed_order(o, report_meta.get(o.id, {})) for o in orders]


@delivery_agent_bp.route("/")
def index():
    if "agent_id" in session:
        return redirect(url_for("delivery_agent.dashboard"))
    return redirect(_agent_login_redirect(session.get("agent_tenant_slug")))


# =====================================================
# Delivery Agent Login Page
# =====================================================
@delivery_agent_bp.route("/login")
def login_page():
    """صفحة تسجيل دخول المندوب"""
    if "agent_id" in session:
        return redirect(url_for("delivery_agent.dashboard"))
    tenant_slug = _normalize_tenant_slug(session.get("tenant_slug"))
    return render_template("delivery_agent/login.html", fixed_tenant_slug=tenant_slug or None)


@delivery_agent_bp.route("/login/<tenant_slug>")
def login_page_tenant(tenant_slug):
    """تسجيل دخول مندوب لشركة محددة عبر الرابط."""
    if "agent_id" in session:
        return redirect(url_for("delivery_agent.dashboard"))
    slug = _normalize_tenant_slug(tenant_slug)
    core_tenant, err = _activate_tenant_slug(slug)
    if err:
        return render_template("delivery_agent/login.html", fixed_tenant_slug=slug, tenant_error=err)
    return render_template(
        "delivery_agent/login.html",
        fixed_tenant_slug=slug,
        tenant_name=core_tenant.name if core_tenant else slug,
    )


def _perform_agent_login(username, password, tenant_slug=None):
    slug = _normalize_tenant_slug(tenant_slug) or _resolve_request_tenant_slug()
    if not slug:
        return None, ("يرجى إدخال معرف الشركة", 400)

    core_tenant, err = _activate_tenant_slug(slug)
    if err:
        return None, (err, 400)

    from utils.agent_passwords import needs_password_rehash, verify_agent_password, hash_agent_password

    agent = DeliveryAgent.query.filter(db.func.lower(DeliveryAgent.username) == username.lower()).first()
    if not agent or not verify_agent_password(agent.password, password):
        return None, ("اسم المستخدم أو كلمة المرور غير صحيحة", 401)
    if not getattr(agent, "is_active", True):
        return None, ("حساب المندوب معطّل", 403)
    if needs_password_rehash(agent.password):
        agent.password = hash_agent_password(password)
        db.session.commit()

    session["agent_id"] = agent.id
    session["agent_name"] = agent.name
    session["agent_role"] = "delivery_agent"
    session["agent_tenant_slug"] = core_tenant.slug
    bind_agent_messaging_session(session, agent, core_tenant.slug)
    return agent, None


@delivery_agent_bp.route("/login", methods=["POST"])
@delivery_agent_bp.route("/login/<tenant_slug>", methods=["POST"])
def login(tenant_slug=None):
    """تسجيل دخول المندوب"""
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    req_tenant = data.get("tenant_slug") or tenant_slug

    if not username or not password:
        return jsonify({"error": "يرجى إدخال اسم المستخدم وكلمة المرور"}), 400

    agent, err = _perform_agent_login(username, password, req_tenant)
    if err:
        return jsonify({"error": err[0]}), err[1]

    return jsonify({
        "success": True,
        "message": "تم تسجيل الدخول بنجاح",
        "redirect": url_for("delivery_agent.dashboard"),
    })

@delivery_agent_bp.route("/logout")
def logout():
    """تسجيل خروج المندوب"""
    tenant_slug = session.get("agent_tenant_slug")
    clear_agent_messaging_session(session)
    session.pop("agent_id", None)
    session.pop("agent_name", None)
    session.pop("agent_role", None)
    session.pop("agent_tenant_slug", None)
    return redirect(_agent_login_redirect(tenant_slug))

# =====================================================
# Delivery Agent Dashboard
# =====================================================
@delivery_agent_bp.route("/dashboard")
def dashboard():
    """صفحة المندوب — طلباته المربوطة باسمه فقط."""
    if "agent_id" not in session:
        return redirect(_agent_login_redirect(session.get("agent_tenant_slug")))
    
    agent_id = session["agent_id"]
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        tenant_slug = session.get("agent_tenant_slug")
        session.pop("agent_id", None)
        session.pop("agent_name", None)
        session.pop("agent_role", None)
        return redirect(_agent_login_redirect(tenant_slug))

    orders = _agent_active_report_orders(agent_id)
    completed_orders = _agent_completed_orders(agent_id)
    stats = _agent_order_stats(agent_id, orders)

    employees = Employee.query.filter_by(is_active=True).all()
    other_agents = DeliveryAgent.query.filter(DeliveryAgent.id != agent_id).filter(DeliveryAgent.username.isnot(None)).all()

    ensure_agent_employee(agent)
    own_employee_id = getattr(agent, "employee_id", None)
    chat_contacts = [
        {"id": employee.id, "name": employee.name, "role": employee.role or ""}
        for employee in employees
        if employee.id != own_employee_id and (employee.role or "") == "admin"
    ]
    
    # التحقق من صلاحيات الأدmin (إذا كان مسجل دخول كأدمن)
    is_admin = session.get("role") == "admin" and "user_id" in session

    return render_template(
        "delivery_agent/dashboard.html",
        agent=agent,
        orders=orders,
        completed_orders=completed_orders,
        stats=stats,
        today=business_date(datetime.utcnow()).isoformat(),
        employees=employees,
        other_agents=other_agents,
        chat_contacts=chat_contacts,
        ready_reports=_ready_manifests(orders),
        is_admin=is_admin,
    )

# =====================================================
# Update Order Status
# =====================================================
@delivery_agent_bp.route("/update-order-status", methods=["POST"])
def update_order_status():
    """حفظ اختيار المندوب في الكشف — التنفيذ النهائي للمحاسب."""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    data = request.json or {}
    order_id = data.get("order_id")
    status = data.get("status")  # واصل، ملغي، مؤجل
    report_id = data.get("report_id")
    agent_id = session["agent_id"]

    if not order_id or not status:
        return jsonify({"error": "بيانات غير كاملة"}), 400

    if status not in ("واصل", "ملغي", "مؤجل"):
        return jsonify({"error": "حالة غير صالحة"}), 400

    scheduled = None
    if status == "مؤجل":
        try:
            scheduled = datetime.strptime(data.get("scheduled_date") or "", "%Y-%m-%d")
        except (ValueError, TypeError):
            return jsonify({"error": "يرجى تحديد تاريخ تأجيل صالح"}), 400
        if scheduled.date() < business_date(datetime.utcnow()):
            return jsonify({"error": "تاريخ التأجيل لا يمكن أن يكون في الماضي"}), 400

    order = Invoice.query.get(order_id)
    if not order:
        return jsonify({"error": "الطلب غير موجود"}), 404

    agent = DeliveryAgent.query.get(agent_id)

    report = _agent_open_report_for_order(agent_id, int(order_id), report_id)

    if order.delivery_agent_id != agent_id and not report:
        return jsonify({"error": "غير مصرح"}), 403

    # إصلاح الربط القديم عند أول تعامل مع طلب موجود فعلاً في كشف هذا المندوب.
    if report and order.delivery_agent_id != agent_id:
        order.delivery_agent_id = agent_id

    if not report:
        from routes.orders import create_agent_report_internal

        result = create_agent_report_internal([int(order_id)], agent_id, save_to_db=True)
        if result.get("error"):
            return jsonify({"error": result["error"]}), 400
        report = ShippingReport.query.get(result.get("report_id"))

    if not report or not is_agent_report(report):
        return jsonify({"error": "تعذر العثور على كشف مندوب للطلب"}), 400

    if report.is_executed:
        return jsonify({"error": "تم تنفيذ هذا الكشف مسبقاً"}), 400

    progress_before = get_report_progress(report)

    if status == "مؤجل":
        order.scheduled_date = scheduled
        order.note = order.note or "مؤجل"
    else:
        order.scheduled_date = None
        if order.note == "مؤجل":
            order.note = None

    progress = save_selection_to_report(report, int(order_id), status)

    if progress["all_complete"] and not progress_before.get("all_complete"):
        notify_agent_report_ready(report, agent.name if agent else "مندوب")

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "تم حفظ الحالة — بانتظار تنفيذ المحاسب",
        "report_id": report.id,
        "report_progress": progress,
        "all_complete": progress["all_complete"],
        "applied_status": status,
        "scheduled_date": order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else None,
        "stats": _agent_order_stats(agent_id, _agent_active_report_orders(agent_id)),
    })


@delivery_agent_bp.route("/update-order-note", methods=["POST"])
def update_order_note():
    """حفظ ملاحظة المندوب على الطلب."""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    data = request.json or {}
    order_id = data.get("order_id")
    report_id = data.get("report_id")
    agent_id = session["agent_id"]
    note_text = (data.get("agent_note") or data.get("note") or "").strip()
    if len(note_text) > 1000:
        return jsonify({"error": "الملاحظة طويلة جداً (الحد 1000 حرف)"}), 400

    if not order_id:
        return jsonify({"error": "بيانات غير كاملة"}), 400

    order = Invoice.query.get(order_id)
    if not order:
        return jsonify({"error": "الطلب غير موجود"}), 404

    report = _agent_open_report_for_order(agent_id, int(order_id), report_id)
    if order.delivery_agent_id != agent_id and not report:
        return jsonify({"error": "غير مصرح"}), 403

    if report and order.delivery_agent_id != agent_id:
        order.delivery_agent_id = agent_id

    order.agent_note = note_text or None
    _sync_agent_note_to_open_report(int(order_id), note_text, report)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "تم حفظ الملاحظة",
        "agent_note": note_text,
        "order_id": int(order_id),
    })


# =====================================================
# Execute Report (Admin Only)
# =====================================================
@delivery_agent_bp.route("/execute-report/<int:report_id>", methods=["POST"])
def execute_report(report_id):
    """تنفيذ الكشف - للأدمن فقط"""
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403

    report = ShippingReport.query.get(report_id)
    if not report:
        return jsonify({"error": "الكشف غير موجود"}), 404

    if not report.orders_data:
        return jsonify({"error": "لا توجد بيانات طلبات في الكشف"}), 400

    data = request.get_json() or {}
    expense_amount = data.get("expense_amount", 0)
    result = execute_shipping_report(
        report,
        expense_amount=expense_amount,
        return_branch_id=data.get("return_branch_id"),
    )
    if result.get("error"):
        return jsonify({"error": result["error"]}), 400
    return jsonify(result)

# =====================================================
# Unified Messages (نفس نظام المراسلة للموظفين)
# =====================================================
@delivery_agent_bp.route("/messages")
def agent_messages():
    """فتح واجهة المراسلة الكاملة للمندوب."""
    if "agent_id" not in session:
        return redirect(_agent_login_redirect(session.get("agent_tenant_slug")))

    agent = DeliveryAgent.query.get(session["agent_id"])
    if not agent:
        return redirect(_agent_login_redirect(session.get("agent_tenant_slug")))

    tenant_slug = session.get("agent_tenant_slug")
    if not tenant_slug:
        return redirect(_agent_login_redirect())

    if not bind_agent_messaging_session(session, agent, tenant_slug):
        return redirect(url_for("delivery_agent.dashboard"))

    return redirect(url_for("messages.messages"))


@delivery_agent_bp.route("/chat/users")
def get_chat_users():
    """توافق قديم — استخدم /delivery-agent/messages."""
    return jsonify({"error": "تم تحديث نظام المحادثة. افتح تبويب المحادثة من جديد."}), 410


@delivery_agent_bp.route("/chat/send", methods=["POST"])
def send_message():
    """توافق قديم — استخدم /messages/send."""
    return jsonify({"error": "تم تحديث نظام المحادثة. افتح تبويب المحادثة من جديد."}), 410


@delivery_agent_bp.route("/chat/messages")
def get_messages():
    """توافق قديم — استخدم /messages/get/<user_id>."""
    return jsonify({"error": "تم تحديث نظام المحادثة. افتح تبويب المحادثة من جديد."}), 410


def _agent_can_see_order(agent_id, order_id):
    order = Invoice.query.get(order_id)
    if not order:
        return None
    if order.delivery_agent_id == agent_id:
        return order
    if _agent_open_report_for_order(agent_id, int(order_id)):
        return order
    return None


@delivery_agent_bp.route("/location", methods=["POST"])
def update_location():
    """آخر موقع للمندوب طالما التطبيق مفتوح."""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    data = request.json or {}
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "إحداثيات غير صالحة"}), 400
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "إحداثيات غير صالحة"}), 400

    def _opt(name):
        value = data.get(name)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    from utils.agent_tracking import record_agent_fix

    record_agent_fix(
        int(session["agent_id"]),
        lat,
        lng,
        accuracy=_opt("accuracy"),
        heading=_opt("heading"),
        speed=_opt("speed"),
    )
    return jsonify({"success": True})


@delivery_agent_bp.route("/route/<int:order_id>")
def order_route(order_id):
    """أقصر مسار قيادة من موقع المندوب إلى الطلب."""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    agent_id = int(session["agent_id"])
    order = _agent_can_see_order(agent_id, order_id)
    if not order:
        return jsonify({"error": "غير مصرح"}), 403
    if order.location_lat is None or order.location_lng is None:
        return jsonify({"error": "الطلب بلا إحداثيات"}), 400

    from utils.agent_tracking import driving_route, latest_position

    try:
        from_lat = float(request.args.get("from_lat")) if request.args.get("from_lat") else None
        from_lng = float(request.args.get("from_lng")) if request.args.get("from_lng") else None
    except (TypeError, ValueError):
        from_lat = from_lng = None
    if from_lat is None or from_lng is None:
        position = latest_position(agent_id)
        if not position:
            return jsonify({"error": "فعّل الموقع أولاً"}), 400
        from_lat, from_lng = position.lat, position.lng

    route = driving_route(from_lat, from_lng, float(order.location_lat), float(order.location_lng))
    if not route.get("ok"):
        return jsonify({
            "success": False,
            "fallback": True,
            "error": route.get("error") or "تعذر حساب الطريق",
            "from": [from_lat, from_lng],
            "to": [order.location_lat, order.location_lng],
        })
    return jsonify({
        "success": True,
        "from": [from_lat, from_lng],
        "to": [float(order.location_lat), float(order.location_lng)],
        "distance": route["distance"],
        "duration": route["duration"],
        "line": route["line"],
        "steps": route["steps"],
    })
