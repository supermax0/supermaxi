"""JSON API reused by Desktop and the authenticated mobile audit surface."""
import json
from functools import wraps

from flask import Response, current_app, jsonify, request, session
from sqlalchemy.exc import IntegrityError, OperationalError

from extensions import db
from modules.desktop_api.routes import desktop_api_bp
from . import service, investigation, posting, offline, transfers, reports
from .common import AuditError, PERMISSIONS, actor, can, command, get_session, require, visible_branches
from .models import InventoryCountSession
from .schema import ensure_schema
from .stock import locations


def endpoint(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            actor()
            require("inventory.audit.view")
            ensure_schema()
            result = fn(*args, **kwargs)
            return result if isinstance(result, (str, Response)) else jsonify({"success": True, "data": result})
        except AuditError as error:
            db.session.rollback()
            return jsonify({"success": False, "error": str(error), "code": error.code}), error.status
        except (IntegrityError, OperationalError):
            db.session.rollback()
            current_app.logger.exception("Inventory audit command failed")
            return jsonify({"success": False, "error": "تعذر حفظ الجرد؛ حدّث البيانات وأعد نفس الطلب", "code": "storage_conflict"}), 409
        except Exception as error:
            from modules.finance.common import FinanceError
            from utils.financial_period_guard import PeriodClosedError
            db.session.rollback()
            if isinstance(error, (FinanceError, PeriodClosedError)):
                return jsonify({"success": False, "error": str(error), "code": getattr(error, "code", "period_closed")}), getattr(error, "status", 400)
            current_app.logger.exception("Inventory audit operation failed")
            return jsonify({"success": False, "error": "تعذر إكمال العملية؛ لم تحفظ تغييراتها", "code": "server_error"}), 500
    return wrapped


def payload():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise AuditError("بيانات الطلب غير صالحة")
    return body


def page_arg(name, default):
    try:
        return int(request.args.get(name, default))
    except (ValueError, TypeError):
        raise AuditError("قيمة الصفحة غير صالحة")


@desktop_api_bp.get("/inventory-audits/meta")
@endpoint
def audit_meta():
    return {"locations": {"branch": locations("branch"), "warehouse": locations("warehouse")},
            "permissions": [key for key in [*PERMISSIONS, "can_manage_inventory", "edit_current_stock", "finance.approve", "can_see_orders", "can_manage_suppliers"] if can(key)],
            "capabilities": {"serial_registry": False, "on_hand": True, "managed_options": True}}


@desktop_api_bp.get("/inventory-audits")
@endpoint
def audit_sessions():
    page, size = page_arg("page", 1), page_arg("page_size", 25)
    service.integer(page, minimum=1, maximum=100000)
    service.integer(size, minimum=1, maximum=100)
    query = InventoryCountSession.query.filter_by(tenant_key=session["tenant_slug"])
    status = request.args.get("status", "")
    if status:
        if status not in ("counting", "paused", "pending_review", "approved", "posted"):
            raise AuditError("حالة الجرد غير صالحة")
        query = query.filter_by(status=status)
    # Scope can contain several locations. Do not expose even a partial session
    # whose remaining sites belong to somebody else's branch.
    allowed = visible_branches()
    rows = [row for row in query.order_by(InventoryCountSession.id.desc())
            if {loc["branch_id"] for loc in json.loads(row.locations_json)} <= allowed]
    return {"items": [service.session_data(row) for row in rows[(page - 1) * size:page * size]],
            "page": page, "page_size": size, "total": len(rows), "total_pages": max(1, (len(rows) + size - 1) // size)}


@desktop_api_bp.post("/inventory-audits")
@endpoint
def audit_create():
    data = payload()
    require("inventory.audit.count")
    return command("create", data, lambda: service.create(data, actor()))


@desktop_api_bp.get("/inventory-audits/<int:session_id>")
@endpoint
def audit_session(session_id):
    row = get_session(session_id)
    result = service.session_data(row)
    if request.args.get("valuation") == "true":
        if row.status == "posted":
            raise AuditError("الجرد مرحّل؛ راجع مطابقة التقييم المحفوظة في سجل الترحيل", "state", 409)
        from .valuation_basis import plan
        result["valuation_review"] = plan(service.validate_counts(row))[0]
    return result


@desktop_api_bp.get("/inventory-audits/<int:session_id>/lines")
@endpoint
def audit_lines(session_id):
    counted = request.args.get("counted")
    if counted not in (None, "true", "false"):
        raise AuditError("مرشح العد غير صالح")
    exact = request.args.get("exact")
    if exact not in (None, "true", "false"):
        raise AuditError("مرشح المطابقة غير صالح")
    return service.search_lines(get_session(session_id), request.args.get("q", ""), request.args.get("location_key"),
        counted=None if counted is None else counted == "true", status=request.args.get("status"),
        page=page_arg("page", 1), page_size=page_arg("page_size", 30), exact=exact == "true")


@desktop_api_bp.get("/inventory-audits/<int:session_id>/history")
@endpoint
def audit_history(session_id):
    return service.history(get_session(session_id), page_arg("line_id", 0), page=page_arg("page", 1), page_size=page_arg("page_size", 30))


@desktop_api_bp.post("/inventory-audits/<int:session_id>/commands")
@endpoint
def audit_commands(session_id):
    data = payload()
    action = data.get("action")
    operations = {"begin_count": ("inventory.audit.count", service.begin_count),
                  "prepare_offline": ("inventory.audit.count", offline.prepare),
                  "save_offline_count": ("inventory.audit.count", offline.save),
                  "transfer_draft": ("inventory.audit.review", transfers.draft),
                  "cancel_count": ("inventory.audit.count", service.cancel_count),
                  "release_ticket": ("inventory.audit.review", service.release_ticket),
                  "save_count": ("inventory.audit.count", service.save_count),
                  "exclude": ("inventory.audit.review", service.exclude),
                  "review_line": ("inventory.audit.review", service.review_line),
                  "submit": ("inventory.audit.count", service.transition),
                  "pause": ("inventory.audit.count", service.transition),
                  "resume": ("inventory.audit.count", service.transition),
                  "reopen": ("inventory.audit.review", service.transition),
                  "approve": ("inventory.audit.approve", service.transition),
                  "investigate": ("inventory.audit.investigate", investigation.investigate),
                  "post": ("inventory.audit.post", posting.post)}
    if action not in operations:
        raise AuditError("إجراء الجرد غير معروف")
    permission, function = operations[action]
    require(permission)
    if action in ("approve", "post"):
        from modules.finance.schema import ensure_schema as finance_schema
        finance_schema()
    return command(action, data, lambda: function(get_session(session_id), data, actor()), session_id=session_id)


@desktop_api_bp.get("/inventory-audits/<int:session_id>/lines/<int:line_id>/details")
@endpoint
def audit_line_details(session_id, line_id):
    row = get_session(session_id)
    line = service.get_line(row, line_id)
    result = {"line": service.line_data(line, inspect_current=row.status != "posted")}
    if can("inventory.audit.investigate") and can("inventory.audit.system"):
        stored = json.loads(line.investigation_json)
        result["investigation"] = investigation.visible_analysis(stored) if stored else None
        if stored:
            result["investigation_stale"] = row.status != "posted" and line.investigation_stamp != investigation.stock_state(line)[1]
    return result


@desktop_api_bp.get("/inventory-audits/<int:session_id>/lines/<int:line_id>/movements")
@endpoint
def audit_line_movements(session_id, line_id):
    require("inventory.audit.investigate")
    line = service.get_line(get_session(session_id), line_id)
    before_id = page_arg("before_id", 0)
    service.integer(before_id)
    return investigation.movements(line, before_id=before_id or None)


@desktop_api_bp.get("/inventory-audits/<int:session_id>/print")
@endpoint
def audit_print(session_id):
    return reports.print_page(get_session(session_id))


@desktop_api_bp.get("/inventory-audits/<int:session_id>/xlsx")
@endpoint
def audit_xlsx(session_id):
    return reports.spreadsheet(get_session(session_id))
