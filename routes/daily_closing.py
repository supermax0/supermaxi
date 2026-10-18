"""Daily closing controller. All mutations are session/company/branch scoped."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_

from extensions import db
from models.daily_closing import (
    DailyCashAdjustment,
    DailyClosingAuditLog,
    DailyInventoryCount,
    DailySession,
    InventoryCountTemplate,
    InventoryCountTemplateItem,
)
from models.activity_log import ActivityLog
from models.branch import Branch, BranchStock
from models.product import Product
from models.stock_movement import StockMovement
from utils.branch_scope import active_branch_id, is_general_admin, resolve_write_branch_id, viewing_all_branches
from utils.daily_closing_schema import ensure_daily_closing_schema
from utils.daily_closing_service import (
    audit,
    archive_snapshot_for_reopen,
    build_daily_closing_data,
    build_period_overview,
    close_session,
    cash_opening_balance,
    company_key,
    linked_data_changed,
    _stock_category,
    _agent_report_order_ids,
    _window,
)
from utils.branch_mode import independent_branches_enabled
from utils.permission_checks import check_permission


daily_closing_bp = Blueprint("daily_closing", __name__, url_prefix="/reports/daily-closing")
IRAQ_TZ = ZoneInfo("Asia/Baghdad")


def _can(permission: str, *, legacy_view: bool = False) -> bool:
    return check_permission(permission) or (legacy_view and check_permission("can_see_reports"))


def _guard(permission: str, *, legacy_view: bool = False):
    if not _can(permission, legacy_view=legacy_view):
        abort(403, description="غير مصرح")


def _payload() -> dict:
    return request.get_json(silent=True) or request.form.to_dict(flat=True)


def _int(value, *, minimum: int | None = None) -> int:
    try:
        parsed = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError("القيمة الرقمية غير صحيحة")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"القيمة يجب ألا تقل عن {minimum}")
    return parsed


def _print_local(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value in (None, ""):
        return "—"
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    elif isinstance(value, datetime):
        parsed = value
    else:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(IRAQ_TZ).strftime(fmt)


def _report_period(business_date: date) -> tuple[datetime | None, datetime | None, str, str]:
    raw_from = (request.args.get("period_from") or "").strip()
    raw_to = (request.args.get("period_to") or "").strip()
    if not raw_from and not raw_to:
        return None, None, "00:00", datetime.now(IRAQ_TZ).strftime("%H:%M")
    try:
        from_time = time.fromisoformat(raw_from or "00:00")
        to_time = time.fromisoformat(raw_to or "23:59")
    except ValueError:
        abort(400, description="الفترة الزمنية غير صحيحة")
    local_start = datetime.combine(business_date, from_time, tzinfo=IRAQ_TZ)
    local_end = datetime.combine(business_date, to_time, tzinfo=IRAQ_TZ)
    if local_end < local_start:
        abort(400, description="وقت نهاية الفترة يجب أن يكون بعد وقت البداية")
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
        raw_from or "00:00",
        raw_to or "23:59",
    )


def _daily_or_404(session_id: int) -> DailySession:
    daily = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
        id=session_id, company_key=company_key()
    ).first_or_404()
    current = active_branch_id()
    employee = getattr(request, "current_employee", None)
    if current and int(daily.branch_id) != int(current) and session.get("role") != "admin":
        abort(404)
    return daily


def _editable(daily: DailySession) -> None:
    if daily.status == "closed":
        abort(409, description="اليومية مغلقة وللقراءة فقط")


def _is_super_admin_user() -> bool:
    """The actual drawer count is intentionally restricted to the top admin."""
    return bool(session.get("is_superadmin") or session.get("role") == "admin")


def _create_automatic_daily(branch_id: int, business_date: date) -> DailySession:
    sequence = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
        company_key=company_key(), business_date=business_date
    ).count() + 1
    daily = DailySession(
        report_number=f"DR-{business_date.strftime('%Y%m%d')}-{sequence:03d}",
        company_key=company_key(),
        branch_id=branch_id,
        business_date=business_date,
        shift_name="تقرير يومي تلقائي",
        opened_by=session.get("user_id"),
        opened_at=datetime.utcnow(),
        opening_cash=cash_opening_balance(branch_id, business_date),
        status="open",
    )
    db.session.add(daily)
    db.session.flush()
    audit(daily, "automatic_create", new={"opening_cash": daily.opening_cash})
    db.session.commit()
    return daily


def _keep_current_daily_open(daily: DailySession) -> DailySession:
    if daily.status == "closed":
        archive_snapshot_for_reopen(daily, reason="تحويل إلى التقرير اليومي الحالي بدون إغلاق")
    old_status = daily.status
    daily.status = "open"
    daily.closed_at = None
    daily.closed_by = None
    daily.snapshot_json = None
    daily.source_fingerprint = None
    if old_status != "open":
        audit(daily, "keep_current_open", old={"status": old_status}, new={"status": "open"})
        db.session.commit()
    return daily


@daily_closing_bp.before_request
def _setup():
    ensure_daily_closing_schema()


@daily_closing_bp.get("")
def dashboard():
    _guard("daily_report.view", legacy_view=True)
    raw_id = request.args.get("session_id", type=int)
    raw_branch = (request.args.get("branch_id") or "").strip().lower()
    all_branch_view = viewing_all_branches()
    shared_mode = not independent_branches_enabled()
    selected_all_branches = (raw_branch == "all" or (not raw_branch and all_branch_view)) and is_general_admin()
    selected_branch_id = None if selected_all_branches else request.args.get("branch_id", type=int)
    if selected_branch_id and (all_branch_view or is_general_admin()):
        selected_branch = Branch.query.filter_by(id=selected_branch_id, is_active=True).first()
        if not selected_branch:
            abort(404)
    elif selected_branch_id and selected_branch_id != active_branch_id():
        abort(403)
    raw_report_date = (request.args.get("report_date") or "").strip()
    try:
        selected_report_date = date.fromisoformat(raw_report_date) if raw_report_date else None
    except ValueError:
        abort(400, description="تاريخ التقرير غير صحيح")
    daily = _daily_or_404(raw_id) if raw_id else None
    if daily is None and not selected_all_branches:
        branch_id = selected_branch_id or active_branch_id()
        if branch_id:
            target_date = selected_report_date or datetime.now(IRAQ_TZ).date()
            daily_query = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
                company_key=company_key(), branch_id=branch_id, business_date=target_date
            )
            daily = daily_query.order_by(DailySession.opened_at.desc()).first()
            if daily is None and target_date == datetime.now(IRAQ_TZ).date():
                daily = _create_automatic_daily(branch_id, target_date)
            elif daily is not None and target_date == datetime.now(IRAQ_TZ).date():
                daily = _keep_current_daily_open(daily)
    open_dailies = []
    if (all_branch_view or shared_mode) and daily is None:
        open_dailies = (
            DailySession.query.execution_options(skip_branch_scope=True)
            .filter(
                DailySession.company_key == company_key(),
                DailySession.status.in_(["open", "under_review"]),
            )
            .order_by(DailySession.opened_at.desc())
            .all()
        )
    period_start = period_end = None
    period_from_value = "00:00"
    period_to_value = datetime.now(IRAQ_TZ).strftime("%H:%M")
    if daily:
        period_start, period_end, period_from_value, period_to_value = _report_period(daily.business_date)
    report_mode = False
    if daily:
        data = build_daily_closing_data(
            daily,
            live=daily.status != "closed" or period_start is not None or period_end is not None,
            period_start=period_start,
            period_end=period_end,
        )
    elif request.args.get("new") != "1":
        report_mode = True
        overview_date = selected_report_date or datetime.now(IRAQ_TZ).date()
        period_start, period_end, period_from_value, period_to_value = _report_period(overview_date)
        if period_start is None:
            local_start = datetime.combine(overview_date, time.min, tzinfo=IRAQ_TZ)
            local_day_end = datetime.combine(overview_date, time.max, tzinfo=IRAQ_TZ)
            local_end = datetime.now(IRAQ_TZ) if overview_date == datetime.now(IRAQ_TZ).date() else local_day_end
            period_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            period_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)
        overview_branch_id = None if selected_all_branches else (selected_branch_id or active_branch_id())
        data = build_period_overview(
            branch_id=overview_branch_id,
            business_date=overview_date,
            period_start=period_start,
            period_end=period_end,
            selected_product_ids=(
                [int(value) for value in (session.get("shared_inventory_product_ids") or []) if str(value).isdigit()]
                if selected_all_branches else None
            ),
        )
    else:
        data = None
    changed = linked_data_changed(daily) if daily and daily.status == "closed" else False
    template_query = InventoryCountTemplate.query.execution_options(skip_branch_scope=True).filter_by(company_key=company_key())
    if daily:
        template_query = template_query.filter(or_(InventoryCountTemplate.branch_id == daily.branch_id, InventoryCountTemplate.branch_id.is_(None)))
    templates = template_query.order_by(InventoryCountTemplate.name).all()
    audit_rows = []
    if daily:
        own_logs = DailyClosingAuditLog.query.filter_by(daily_session_id=daily.id, company_key=company_key()).all()
        audit_rows = [{
            "created_at": row.created_at, "action": row.action,
            "user_name": row.user_name, "user_id": row.user_id,
            "old_value_json": row.old_value_json, "new_value_json": row.new_value_json,
            "reason": row.reason,
        } for row in own_logs]
        end_at = daily.closed_at or datetime.utcnow()
        try:
            expense_logs = (
                ActivityLog.query.execution_options(skip_branch_scope=True)
                .filter(
                    ActivityLog.branch_id == daily.branch_id,
                    ActivityLog.entity_type == "expense",
                    ActivityLog.created_at >= daily.opened_at,
                    ActivityLog.created_at <= end_at,
                ).all()
            )
        except Exception:
            db.session.rollback()
            expense_logs = []
        audit_rows.extend({
            "created_at": row.created_at, "action": f"expense_{row.action}",
            "user_name": row.employee_name, "user_id": row.employee_id,
            "old_value_json": json.dumps(row.get_payload().get("expense"), ensure_ascii=False) if row.action == "delete" else None,
            "new_value_json": json.dumps(row.get_payload(), ensure_ascii=False),
            "reason": row.summary,
        } for row in expense_logs)
        audit_rows.sort(key=lambda row: row["created_at"] or datetime.min, reverse=True)
        audit_rows = audit_rows[:100]
    return render_template(
        "daily_closing.html", daily=daily, report=data, templates=templates, audit_rows=audit_rows,
        linked_data_changed=changed,
        open_dailies=open_dailies, selected_branch_id=selected_branch_id,
        selected_all_branches=selected_all_branches,
        all_branch_view=all_branch_view,
        now_date=datetime.now(IRAQ_TZ).date().isoformat(),
        report_branches=Branch.query.execution_options(skip_branch_scope=True).filter_by(is_active=True).order_by(Branch.name).all(),
        report_date_value=(daily.business_date.isoformat() if daily else (selected_report_date.isoformat() if selected_report_date else datetime.now(IRAQ_TZ).date().isoformat())),
        period_from_value=period_from_value,
        period_to_value=period_to_value,
        can_switch_report_branch=is_general_admin(),
        shared_mode=shared_mode,
        shared_branches=Branch.query.execution_options(skip_branch_scope=True).filter_by(is_active=True).order_by(Branch.name).all(),
        report_mode=report_mode,
        view_session=(daily if daily else (type("ReportView", (), {
            "id": None,
            "branch_id": (data or {}).get("session", {}).get("branch_id"),
            "business_date": date.fromisoformat((data or {}).get("session", {}).get("business_date", datetime.now(IRAQ_TZ).date().isoformat())),
            "status": "report",
        })() if data else None)),
        permissions={name: _can(name, legacy_view=name == "daily_report.view") for name in (
            "daily_report.view", "daily_report.create", "daily_report.edit", "daily_report.close",
            "daily_report.reopen", "daily_report.print", "daily_report.export",
            "daily_report.inventory_count", "daily_report.override_variance",
        )} | {"can_edit_actual_cash": _is_super_admin_user()},
    )


@daily_closing_bp.post("/start")
def start():
    _guard("daily_report.create")
    payload = _payload()
    shared_mode = not independent_branches_enabled()
    if shared_mode and payload.get("open_all_shared") in (True, "true", "1", 1):
        active = Branch.query.execution_options(skip_branch_scope=True).filter_by(is_active=True).order_by(Branch.id).all()
        active_by_id = {int(branch.id): branch for branch in active}
        raw_rows = payload.get("branches") or []
        if not raw_rows and payload.get("opening_cash") not in (None, ""):
            raw_rows = [{"branch_id": branch.id, "opening_cash": payload.get("opening_cash")} for branch in active]
        if not isinstance(raw_rows, list) or not raw_rows:
            return jsonify({"success": False, "error": "يجب إدخال رصيد الصندوق المشترك"}), 400
        rows = []
        seen = set()
        for raw in raw_rows:
            try:
                branch_id = int(raw.get("branch_id"))
                opening_cash = _int(raw.get("opening_cash", 0), minimum=0)
            except (AttributeError, TypeError, ValueError) as exc:
                return jsonify({"success": False, "error": str(exc) or "بيانات الفرع غير صحيحة"}), 400
            if branch_id not in active_by_id or branch_id in seen:
                continue
            seen.add(branch_id)
            rows.append((branch_id, opening_cash))
        if {branch_id for branch_id, _ in rows} != set(active_by_id):
            return jsonify({"success": False, "error": "يجب إدخال رصيد الصندوق لكل الفروع المشتركة"}), 400
        business_date = date.today()
        raw_date = payload.get("business_date")
        if raw_date:
            try:
                business_date = date.fromisoformat(raw_date)
            except ValueError:
                return jsonify({"success": False, "error": "التاريخ غير صحيح"}), 400
        existing = DailySession.query.execution_options(skip_branch_scope=True).filter(
            DailySession.company_key == company_key(),
            DailySession.branch_id.in_(active_by_id),
            DailySession.status.in_(["open", "under_review"]),
        ).all()
        if existing:
            return jsonify({
                "success": False,
                "error": "توجد يومية مفتوحة لأحد الفروع المشتركة",
                "session_id": existing[0].id,
                "url": url_for("daily_closing.dashboard", session_id=existing[0].id),
            }), 409
        created = []
        for index, (branch_id, opening_cash) in enumerate(rows, start=1):
            sequence = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
                company_key=company_key(), business_date=business_date
            ).count() + 1
            daily = DailySession(
                report_number=f"DR-{business_date.strftime('%Y%m%d')}-{sequence:03d}", company_key=company_key(),
                branch_id=branch_id, business_date=business_date,
                shift_name=(payload.get("shift_name") or "عام")[:100], opened_by=session.get("user_id"),
                opened_at=datetime.utcnow(), opening_cash=opening_cash, status="open",
            )
            db.session.add(daily)
            db.session.flush()
            audit(daily, "create", new={"opening_cash": opening_cash, "shift_name": daily.shift_name, "shared_start": True})
            created.append(daily)
        db.session.commit()
        return jsonify({"success": True, "session_id": created[0].id, "url": url_for("daily_closing.dashboard", session_id=created[0].id), "session_ids": [item.id for item in created]})
    if viewing_all_branches() and payload.get("branch_id") in (None, "", 0, "0", "all"):
        return jsonify({"success": False, "error": "يجب اختيار الفرع صراحةً قبل بدء اليومية"}), 400
    branch_id = resolve_write_branch_id(payload, required=True)
    key = company_key()
    existing = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
        company_key=key, branch_id=branch_id
    ).filter(DailySession.status.in_(["open", "under_review"])).first()
    if existing:
        return jsonify({"success": False, "error": "توجد يومية مفتوحة لهذا الفرع", "session_id": existing.id}), 409
    business_date = date.today()
    raw_date = payload.get("business_date")
    if raw_date:
        try:
            business_date = date.fromisoformat(raw_date)
        except ValueError:
            return jsonify({"success": False, "error": "التاريخ غير صحيح"}), 400
    sequence = DailySession.query.execution_options(skip_branch_scope=True).filter_by(
        company_key=key, business_date=business_date
    ).count() + 1
    daily = DailySession(
        report_number=f"DR-{business_date.strftime('%Y%m%d')}-{sequence:03d}", company_key=key,
        branch_id=branch_id, business_date=business_date, shift_name=(payload.get("shift_name") or "عام")[:100],
        opened_by=session.get("user_id"), opened_at=datetime.utcnow(), opening_cash=_int(payload.get("opening_cash", 0), minimum=0),
        status="open",
    )
    db.session.add(daily)
    db.session.flush()
    audit(daily, "create", new={"opening_cash": daily.opening_cash, "shift_name": daily.shift_name})
    db.session.commit()
    return jsonify({"success": True, "session_id": daily.id, "url": url_for("daily_closing.dashboard", session_id=daily.id)})


@daily_closing_bp.post("/<int:session_id>/save")
def save(session_id: int):
    _guard("daily_report.edit")
    daily = _daily_or_404(session_id)
    _editable(daily)
    payload = _payload()
    old = {"actual_closing_cash": daily.actual_closing_cash, "notes": daily.notes, "status": daily.status}
    if "actual_closing_cash" in payload:
        if not _is_super_admin_user():
            return jsonify({"success": False, "error": "تغيير الصندوق الحالي متاح للسوبر أدمن فقط"}), 403
        daily.actual_closing_cash = (
            None if payload.get("actual_closing_cash") in (None, "")
            else _int(payload["actual_closing_cash"], minimum=0)
        )
    if "notes" in payload:
        daily.notes = str(payload.get("notes") or "").strip() or None
    # The daily report always remains current/open; it is no longer moved to
    # an under-review state when its live values are saved.
    daily.status = "open"
    report = build_daily_closing_data(daily)
    daily.expected_closing_cash = int(report["cash"]["expected"])
    daily.cash_variance = report["cash"]["variance"]
    audit(daily, "save", old=old, new={
        "actual_closing_cash": daily.actual_closing_cash,
        "cash_variance": daily.cash_variance,
        "notes": daily.notes,
        "status": daily.status,
    })
    db.session.commit()
    return jsonify({"success": True, "report": report})


@daily_closing_bp.get("/<int:session_id>/refresh")
def refresh(session_id: int):
    _guard("daily_report.view", legacy_view=True)
    daily = _daily_or_404(session_id)
    return jsonify({"success": True, "report": build_daily_closing_data(daily, live=daily.status != "closed")})


@daily_closing_bp.get("/<int:session_id>/stock-details")
def stock_details(session_id: int):
    _guard("daily_report.view", legacy_view=True)
    daily = _daily_or_404(session_id)
    product_id = request.args.get("product_id", type=int)
    category = (request.args.get("category") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("per_page", 30, type=int)))
    if not product_id or not category:
        return jsonify({"success": False, "error": "المادة ونوع الحركة مطلوبان"}), 400
    if daily.status == "closed" and daily.snapshot_json:
        source = (json.loads(daily.snapshot_json).get("stock") or {}).get("details") or []
        rows = [row for row in source if int(row.get("product_id") or 0) == product_id and row.get("category") == category]
    else:
        end_at = daily.closed_at or datetime.utcnow()
        window_start, window_end = _window(daily, end_at=end_at)
        courier_order_ids = _agent_report_order_ids(daily, window_start, window_end)
        source = (
            StockMovement.query.execution_options(skip_branch_scope=True)
            .filter(
                StockMovement.branch_id == daily.branch_id,
                StockMovement.product_id == product_id,
                StockMovement.created_at >= window_start,
                StockMovement.created_at <= window_end,
            ).order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).all()
        )
        rows = [{
            "id": row.id, "time": row.created_at.isoformat(), "product_id": row.product_id,
            "product_name": row.product.name if row.product else f"مادة #{row.product_id}",
            "movement_type": row.movement_type, "direction": row.direction,
            "category": "other_out" if _stock_category(row, courier_order_ids) == "other" else _stock_category(row, courier_order_ids),
            "quantity": int(row.quantity or 0), "reference_type": row.source_type,
            "reference_id": row.source_id, "reference_line_id": row.source_line_id,
        } for row in source]
        rows = [row for row in rows if row["category"] == category]
    total = len(rows)
    start_at = (page - 1) * per_page
    return jsonify({"success": True, "rows": rows[start_at:start_at + per_page], "page": page, "pages": max(1, (total + per_page - 1) // per_page), "total": total})


@daily_closing_bp.get("/products")
def products():
    _guard("daily_report.inventory_count")
    requested_branch_id = request.args.get("branch_id", type=int)
    # Legacy shared mode exposes the same catalogue/cash context for all
    # physical branches, so a requested branch must not be rejected merely
    # because it is not the session's default branch.
    if requested_branch_id and independent_branches_enabled() and not viewing_all_branches() and requested_branch_id != active_branch_id():
        abort(403)
    if requested_branch_id and not Branch.query.filter_by(id=requested_branch_id, is_active=True).first():
        abort(404)
    branch_id = requested_branch_id or (
        None if (viewing_all_branches() or not independent_branches_enabled())
        else active_branch_id()
    )
    all_branch_mode = branch_id is None and (viewing_all_branches() or not independent_branches_enabled())
    search = (request.args.get("q") or "").strip()
    query = Product.query.execution_options(skip_branch_scope=True).filter(Product.active.is_(True))
    if branch_id:
        query = query.filter(or_(Product.branch_id == branch_id, Product.branch_id.is_(None)))
    if search:
        query = query.filter(or_(Product.name.ilike(f"%{search}%"), Product.barcode.ilike(f"%{search}%"), Product.sku.ilike(f"%{search}%")))
    rows = query.order_by(Product.name).limit(500 if all_branch_mode else 250).all()
    branch_quantities = {}
    if branch_id and rows:
        branch_quantities = {
            int(product_id): int(quantity or 0)
            for product_id, quantity in (
                db.session.query(BranchStock.product_id, BranchStock.quantity)
                .execution_options(skip_branch_scope=True)
                .filter(BranchStock.branch_id == branch_id, BranchStock.product_id.in_([row.id for row in rows]))
                .all()
            )
        }
    if all_branch_mode and rows:
        all_stock = db.session.query(
            BranchStock.product_id, func.sum(BranchStock.quantity)
        ).execution_options(skip_branch_scope=True).filter(
            BranchStock.product_id.in_([row.id for row in rows])
        ).group_by(BranchStock.product_id).all()
        branch_quantities = {int(product_id): int(quantity or 0) for product_id, quantity in all_stock}
    products_payload = []
    for row in rows:
        try:
            metadata = json.loads(row.meta_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        products_payload.append({
            "id": row.id, "name": row.name, "category": row.catalog_category or metadata.get("category") or "بدون تصنيف",
            "brand": str(metadata.get("brand") or "بدون ماركة"),
            "sku": row.sku or "", "barcode": row.barcode or "", "branch_id": row.branch_id,
            "available_quantity": branch_quantities.get(row.id, int(row.quantity or 0)),
        })
    if all_branch_mode:
        merged_products = {}
        for item in products_payload:
            barcode = str(item.get("barcode") or "").strip().casefold()
            sku = str(item.get("sku") or "").strip().casefold()
            key = f"barcode:{barcode}" if barcode else (f"sku:{sku}" if sku else f"name:{str(item.get('name') or '').strip().casefold()}")
            existing = merged_products.get(key)
            if existing is None:
                merged_products[key] = dict(item)
            else:
                existing["available_quantity"] += int(item.get("available_quantity") or 0)
        products_payload = sorted(merged_products.values(), key=lambda item: str(item.get("name") or "").casefold())
    return jsonify({"success": True, "branch_id": branch_id, "products": products_payload})


@daily_closing_bp.post("/shared-inventory/items")
def save_shared_inventory_items():
    _guard("daily_report.inventory_count")
    payload = request.get_json(silent=True) or {}
    ids = sorted({int(value) for value in (payload.get("product_ids") or []) if str(value).isdigit()})
    session["shared_inventory_product_ids"] = ids
    return jsonify({"success": True, "product_ids": ids})


@daily_closing_bp.post("/<int:session_id>/inventory/items")
def add_inventory_items(session_id: int):
    _guard("daily_report.inventory_count")
    daily = _daily_or_404(session_id)
    _editable(daily)
    payload = request.get_json(silent=True) or {}
    product_ids = sorted({_int(value, minimum=1) for value in payload.get("product_ids", [])})
    valid_ids = {
        row.id for row in Product.query.execution_options(skip_branch_scope=True).filter(
            Product.id.in_(product_ids),
            or_(Product.branch_id == daily.branch_id, Product.branch_id.is_(None)),
        ).all()
    } if product_ids else set()
    existing = {row.product_id for row in daily.counts}
    for product_id in valid_ids - existing:
        db.session.add(DailyInventoryCount(
            daily_session_id=daily.id, company_key=daily.company_key, branch_id=daily.branch_id,
            product_id=product_id, warehouse_id=0,
        ))
    audit(daily, "inventory_items_add", new={"product_ids": sorted(valid_ids - existing)})
    db.session.commit()
    return jsonify({"success": True, "report": build_daily_closing_data(daily)})


@daily_closing_bp.delete("/<int:session_id>/inventory/items/<int:count_id>")
def remove_inventory_item(session_id: int, count_id: int):
    _guard("daily_report.inventory_count")
    daily = _daily_or_404(session_id)
    _editable(daily)
    count = DailyInventoryCount.query.filter_by(id=count_id, daily_session_id=daily.id, company_key=daily.company_key).first_or_404()
    old = {"product_id": count.product_id, "actual": count.actual_quantity}
    db.session.delete(count)
    audit(daily, "inventory_item_remove", entity_type="inventory_count", entity_id=count.id, old=old)
    db.session.commit()
    return jsonify({"success": True})


@daily_closing_bp.patch("/<int:session_id>/inventory/items/<int:count_id>")
def update_inventory_item(session_id: int, count_id: int):
    _guard("daily_report.inventory_count")
    daily = _daily_or_404(session_id)
    _editable(daily)
    count = DailyInventoryCount.query.filter_by(id=count_id, daily_session_id=daily.id, company_key=daily.company_key).first_or_404()
    payload = request.get_json(silent=True) or {}
    old = {"actual": count.actual_quantity, "notes": count.notes}
    count.actual_quantity = _int(payload.get("actual_quantity"), minimum=0)
    count.notes = str(payload.get("notes") or "").strip() or None
    count.counted_by = session.get("user_id")
    count.counted_at = datetime.utcnow()
    audit(daily, "inventory_count_update", entity_type="inventory_count", entity_id=count.id, old=old, new={"actual": count.actual_quantity, "notes": count.notes})
    db.session.commit()
    return jsonify({"success": True, "report": build_daily_closing_data(daily)})


@daily_closing_bp.post("/<int:session_id>/templates")
def save_template(session_id: int):
    _guard("daily_report.inventory_count")
    daily = _daily_or_404(session_id)
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "اسم قائمة الجرد مطلوب"}), 400
    template = InventoryCountTemplate.query.filter_by(company_key=daily.company_key, branch_id=daily.branch_id, name=name).first()
    if not template:
        template = InventoryCountTemplate(company_key=daily.company_key, branch_id=daily.branch_id, name=name[:150], created_by=session.get("user_id"))
        db.session.add(template)
        db.session.flush()
    template.items = [InventoryCountTemplateItem(product_id=row.product_id, warehouse_id=row.warehouse_id) for row in daily.counts]
    audit(daily, "inventory_template_save", entity_type="inventory_template", entity_id=template.id, new={"name": name, "product_ids": [row.product_id for row in daily.counts]})
    db.session.commit()
    return jsonify({"success": True, "template_id": template.id})


@daily_closing_bp.post("/<int:session_id>/templates/<int:template_id>/apply")
def apply_template(session_id: int, template_id: int):
    _guard("daily_report.inventory_count")
    daily = _daily_or_404(session_id)
    _editable(daily)
    template = InventoryCountTemplate.query.execution_options(skip_branch_scope=True).filter(
        InventoryCountTemplate.id == template_id,
        InventoryCountTemplate.company_key == daily.company_key,
        or_(InventoryCountTemplate.branch_id == daily.branch_id, InventoryCountTemplate.branch_id.is_(None)),
    ).first_or_404()
    existing = {row.product_id for row in daily.counts}
    template_product_ids = [item.product_id for item in template.items]
    valid_product_ids = {
        row.id for row in Product.query.execution_options(skip_branch_scope=True).filter(
            Product.id.in_(template_product_ids),
            or_(Product.branch_id == daily.branch_id, Product.branch_id.is_(None)),
        ).all()
    }
    for item in template.items:
        if item.product_id in valid_product_ids and item.product_id not in existing:
            db.session.add(DailyInventoryCount(daily_session_id=daily.id, company_key=daily.company_key, branch_id=daily.branch_id, product_id=item.product_id, warehouse_id=item.warehouse_id))
    audit(daily, "inventory_template_apply", entity_type="inventory_template", entity_id=template.id, new={"name": template.name})
    db.session.commit()
    return jsonify({"success": True, "report": build_daily_closing_data(daily)})


@daily_closing_bp.post("/<int:session_id>/cash-adjustments")
def add_cash_adjustment(session_id: int):
    _guard("daily_report.edit")
    daily = _daily_or_404(session_id)
    _editable(daily)
    payload = request.get_json(silent=True) or {}
    direction = payload.get("direction")
    if direction not in {"in", "out"}:
        return jsonify({"success": False, "error": "اتجاه الحركة غير صحيح"}), 400
    reference = str(payload.get("reference") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not reference or not description:
        return jsonify({"success": False, "error": "المرجع والبيان مطلوبان"}), 400
    row = DailyCashAdjustment(
        daily_session_id=daily.id, company_key=daily.company_key, direction=direction,
        category=str(payload.get("category") or "CASH_ADJUSTMENT")[:40], amount=_int(payload.get("amount"), minimum=1),
        description=description[:255], reference=reference[:120], created_by=session.get("user_id"),
    )
    db.session.add(row)
    db.session.flush()
    audit(daily, "cash_adjustment_add", entity_type="cash_adjustment", entity_id=row.id, new={"direction": direction, "amount": row.amount, "reference": reference})
    db.session.commit()
    return jsonify({"success": True, "report": build_daily_closing_data(daily)})


@daily_closing_bp.post("/<int:session_id>/close")
def close(session_id: int):
    _guard("daily_report.close")
    _daily_or_404(session_id)
    return jsonify({"success": False, "error": "تم إلغاء إغلاق اليومية؛ التقرير يبقى حالياً ومفتوحاً دائماً"}), 410


@daily_closing_bp.post("/<int:session_id>/reopen")
def reopen(session_id: int):
    _guard("daily_report.reopen")
    daily = _daily_or_404(session_id)
    if daily.status != "closed":
        return jsonify({"success": False, "error": "اليومية ليست مغلقة"}), 409
    other_open = DailySession.query.execution_options(skip_branch_scope=True).filter(
        DailySession.company_key == daily.company_key,
        DailySession.branch_id == daily.branch_id,
        DailySession.id != daily.id,
        DailySession.status.in_(["open", "under_review"]),
    ).first()
    if other_open:
        return jsonify({"success": False, "error": f"لا يمكن إعادة الفتح بوجود يومية مفتوحة ({other_open.report_number})"}), 409
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if not reason:
        return jsonify({"success": False, "error": "سبب إعادة الفتح مطلوب"}), 400
    old = {"status": daily.status, "closed_at": daily.closed_at, "closed_by": daily.closed_by, "snapshot": bool(daily.snapshot_json)}
    archived = archive_snapshot_for_reopen(daily, reason=reason)
    daily.status = "open"
    daily.reopened_by = session.get("user_id")
    daily.reopened_at = datetime.utcnow()
    daily.reopen_reason = reason
    audit(daily, "reopen", old=old, new={"status": "open", "archived_snapshot_id": archived.id if archived else None, "next_snapshot_version": daily.snapshot_version}, reason=reason)
    db.session.commit()
    return jsonify({"success": True})


@daily_closing_bp.get("/<int:session_id>/print")
def print_report(session_id: int):
    if not (_can("daily_report.print") or _can("daily_report.export")):
        abort(403)
    daily = _daily_or_404(session_id)
    data = build_daily_closing_data(daily, live=daily.status != "closed")
    default_sections = ["sales", "cash", "cash_details", "expenses", "stock_out", "stock_in", "couriers", "returns", "inventory", "audit", "notes", "signatures"]
    sections = request.args.getlist("section") or default_sections
    mode = request.args.get("mode") if request.args.get("mode") in {"summary", "detailed"} else "detailed"
    audit_rows = (
        DailyClosingAuditLog.query.execution_options(skip_branch_scope=True)
        .filter_by(daily_session_id=daily.id, company_key=daily.company_key)
        .order_by(DailyClosingAuditLog.created_at.desc(), DailyClosingAuditLog.id.desc())
        .limit(100)
        .all()
    )
    html = render_template(
        "daily_closing_print.html", report=data, sections=set(sections), mode=mode,
        printed_by=session.get("name") or "Finora", printed_at=datetime.now(IRAQ_TZ),
        auto_print=request.args.get("auto_print") == "1" and request.args.get("download") != "1",
        audit_rows=audit_rows, format_local_datetime=_print_local,
    )
    if request.args.get("download") != "1":
        return html
    try:
        from weasyprint import HTML
    except ImportError:
        abort(503, description="خدمة إنشاء PDF غير متاحة حالياً")
    pdf = HTML(string=html, base_url=request.url_root).write_pdf()
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{daily.report_number}.pdf"'
    response.headers["Cache-Control"] = "private, no-store"
    return response
