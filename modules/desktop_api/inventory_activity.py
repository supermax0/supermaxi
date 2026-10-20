"""Read-only inventory evidence, without reconstructing undocumented balances."""
from utils.time_format import format_timestamp
import csv
import io
import json
from datetime import date, datetime, time, timedelta

from flask import jsonify, request, render_template
from sqlalchemy import case, inspect, literal, select, union_all

from extensions import db
from models.branch import Branch, BranchStock
from models.inventory_audit import InventoryQuantityAudit as Audit
from models.product import Product
from models.stock_movement import StockMovement as Movement
from modules.desktop_api.routes import desktop_api_bp
from modules.inventory_audit.common import AuditError, actor, visible_branches
from utils.permission_checks import employee_can

LABELS = {"purchase_receive": "استلام شراء", "purchase_reverse": "عكس شراء",
          "transfer_send": "إرسال تحويل", "transfer_receive": "استلام تحويل", "transfer_cancel": "إلغاء تحويل",
          "order_branch_release": "إرجاع حجز طلب", "order_branch_reserve": "تحويل حجز طلب",
          "inventory_count_adjustment": "تسوية جرد", "inventory_writeoff": "تلف مخزون", "inventory_writeoff_reversal": "عكس تلف مخزون", "unclassified_adjustment": "تعديل غير مصنف"}
SOURCES = {"invoice": "فاتورة بيع", "purchase": "فاتورة شراء", "stock_transfer": "تحويل مخزون",
           "trade_in_receipt": "استلام استبدال", "trade_in_reversal": "عكس استلام استبدال",
           "inventory_count": "تسوية جرد", "inventory_writeoff": "تلف / عكس تلف", "direct_stock_change": "تغيير مباشر", "database_trigger": "تغيير ملتقط"}


def _number(name, default=None, maximum=1000000000):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if len(raw) > 10 or not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= maximum:
        raise AuditError("قيمة التصفية غير صالحة")
    return int(raw)


def _dates():
    values = []
    for key in ("from", "to"):
        raw = request.args.get(key)
        if not raw:
            values.append(None)
            continue
        try:
            value = date.fromisoformat(raw)
            if value.isoformat() != raw or not 2 <= value.year <= 9998:
                raise ValueError()
            values.append(value)
        except ValueError:
            raise AuditError("استخدم تاريخاً صحيحاً بصيغة سنة-شهر-يوم")
    if all(values) and values[0] > values[1]:
        raise AuditError("تاريخ البداية بعد تاريخ النهاية")
    return values


def _details(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _cost(value):
    # Preserve whole dinars when an aggregate exceeds JavaScript's safe integer range.
    return str(value) if value is not None and abs(value) > 9007199254740991 else value


def _evidence(tables):
    # A linked before/after audit is supporting evidence, not another movement.
    movements = select(
        literal("movement").label("record_kind"), Movement.id.label("record_id"),
        Movement.product_id, Movement.branch_id, Movement.created_at,
        Movement.movement_type.label("operation"), Movement.direction, Movement.quantity,
        Movement.source_type, Movement.source_id, Movement.unit_cost, Movement.total_cost,
    )
    captured = select(
        literal("capture").label("record_kind"), Audit.id.label("record_id"),
        Audit.product_id, Audit.branch_id, Audit.created_at,
        Audit.operation.label("operation"),
        case((Audit.delta_quantity > 0, "in"), else_="out").label("direction"),
        db.func.abs(Audit.delta_quantity).label("quantity"),
        Audit.source_type, Audit.source_id,
        literal(None).label("unit_cost"), literal(None).label("total_cost"),
    ).where(Audit.movement_id.is_(None), Audit.delta_quantity != 0)
    if BranchStock.__tablename__ in tables:
        # Product.quantity can be a projection of branch balances. A mirror
        # update must not appear as a second physical receipt or deduction.
        projection = db.func.replace(db.func.coalesce(Audit.metadata_json, ""), " ", "").contains(
            '"scope":"product.quantity"')
        physical = select(BranchStock.id).where(BranchStock.product_id == Audit.product_id).exists()
        captured = captured.where(~db.and_(projection, physical))
    return union_all(movements, captured).subquery()


def _sources(rows, user, allowed, tables):
    """References do not grant permission to open a source in another branch."""
    from models.invoice import Invoice
    from models.purchase import Purchase
    from models.branch import StockTransfer
    from modules.inventory_audit.models import InventoryCountSession
    available = {}
    for kind, model, permission in (("invoice", Invoice, "can_see_orders"),
                                    ("purchase", Purchase, "can_manage_suppliers")):
        if model.__tablename__ in tables and employee_can(user, permission):
            ids = [r["source_id"] for r in rows if r["source_type"] == kind and r["source_id"]]
            if kind == "invoice":
                from utils.permission_checks import employee_can_access_order
                found = db.session.execute(select(model).where(model.id.in_(ids), model.branch_id.in_(allowed))
                                           .execution_options(skip_branch_scope=True)).scalars()
                available.update({(kind, row.id): (kind, row.id) for row in found if employee_can_access_order(user, row)})
            else:
                found = db.session.execute(select(model.id).where(model.id.in_(ids), model.branch_id.in_(allowed))
                                           .execution_options(skip_branch_scope=True)).scalars()
                available.update({(kind, value): (kind, value) for value in found})
    if InventoryCountSession.__tablename__ in tables and employee_can(user, "inventory.audit.view"):
        ids = [r["source_id"] for r in rows if r["source_type"] == "inventory_count" and r["source_id"]]
        from flask import session
        for row in InventoryCountSession.query.filter(InventoryCountSession.id.in_(ids),
                                                       InventoryCountSession.tenant_key == session["tenant_slug"]):
            if {location["branch_id"] for location in _locations(row.locations_json)} <= allowed:
                available[("inventory_count", row.id)] = ("inventory_count", row.id)
    ids = [r["source_id"] for r in rows if r["source_type"] == "stock_transfer" and r["source_id"]]
    if StockTransfer.__tablename__ in tables:
        found = db.session.execute(select(StockTransfer.id).where(StockTransfer.id.in_(ids), db.or_(
            StockTransfer.from_branch_id.in_(allowed), StockTransfer.to_branch_id.in_(allowed)))
            .execution_options(skip_branch_scope=True)).scalars()
        available.update({("stock_transfer", value): ("stock_transfer", value) for value in found})
    from models.trade_in_receipt import TradeInReceipt
    if {TradeInReceipt.__tablename__, Invoice.__tablename__} <= tables and employee_can(user, "can_see_orders"):
        from utils.permission_checks import employee_can_access_order
        ids = [r["source_id"] for r in rows if r["source_type"] in ("trade_in_receipt", "trade_in_reversal") and r["source_id"]]
        found = db.session.execute(select(TradeInReceipt.id, Invoice).join(Invoice, Invoice.id == TradeInReceipt.invoice_id)
            .where(TradeInReceipt.id.in_(ids), TradeInReceipt.branch_id.in_(allowed), Invoice.branch_id.in_(allowed))
            .execution_options(skip_branch_scope=True)).all()
        for receipt_id, invoice in found:
            if employee_can_access_order(user, invoice):
                for kind in ("trade_in_receipt", "trade_in_reversal"):
                    available[(kind, receipt_id)] = ("invoice", invoice.id)
    from models.stock_operations import InventoryWriteOff
    if InventoryWriteOff.__tablename__ in tables:
        ids = [r["source_id"] for r in rows if r["source_type"] == "inventory_writeoff" and r["source_id"]]
        found = InventoryWriteOff.query.execution_options(skip_branch_scope=True).filter(
            InventoryWriteOff.id.in_(ids), InventoryWriteOff.branch_id.in_(allowed), InventoryWriteOff.ledger_kind == "branch")
        available.update({("inventory_writeoff", row.id): ("inventory_writeoff", row.id) for row in found})
    return available


def _locations(raw):
    try:
        result = json.loads(raw)
        if isinstance(result, list) and result and all(isinstance(x, dict) and type(x.get("branch_id")) is int for x in result):
            return result
    except (ValueError, TypeError):
        pass
    return [{"branch_id": -1}]


def _list(user, *, report=False):
    allowed = visible_branches()
    branch_id = _number("branch_id")
    if branch_id is not None and branch_id not in allowed:
        raise AuditError("الفرع خارج نطاق صلاحياتك", "forbidden", 403)
    page, size = _number("page", 1, 100000), _number("page_size", 25, 100)
    if report:
        page, size = 1, 20000
    product_id = _number("product_id")
    start, end = _dates()
    direction = request.args.get("direction", "")
    if direction not in ("", "in", "out"):
        raise AuditError("اتجاه الحركة غير صالح")
    search = request.args.get("q", "").strip()
    if len(search) > 150:
        raise AuditError("نص البحث أطول من الحد المسموح")
    bind = db.session.get_bind()
    tables = set(inspect(bind).get_table_names())
    if not {Movement.__tablename__, Audit.__tablename__} <= tables:
        return {"available": False, "items": [], "total": 0, "page": page, "page_size": size,
                "branches": [], "can_view_cost": False,
                "notice": "سجل الحركة غير مهيأ لهذه الشركة؛ لم يتم إنشاء جداول أثناء العرض."}
    evidence = _evidence(tables)
    query = select(evidence, Product.name.label("product_name"), Product.sku, Branch.name.label("branch_name")).select_from(evidence)\
        .join(Product, Product.id == evidence.c.product_id).join(Branch, Branch.id == evidence.c.branch_id)\
        .where(evidence.c.branch_id.in_([branch_id] if branch_id else allowed))\
        .execution_options(skip_branch_scope=True)
    if product_id:
        group = db.session.execute(select(Product.catalog_group_id).where(Product.id == product_id)
                                   .execution_options(skip_branch_scope=True)).scalar_one_or_none()
        query = query.where(Product.catalog_group_id == group) if group else query.where(evidence.c.product_id == product_id)
    if direction:
        query = query.where(evidence.c.direction == direction)
    if start:
        query = query.where(evidence.c.created_at >= datetime.combine(start, time.min) - timedelta(hours=3))
    if end:
        query = query.where(evidence.c.created_at < datetime.combine(end + timedelta(days=1), time.min) - timedelta(hours=3))
    if search:
        query = query.where(db.or_(Product.name.contains(search, autoescape=True),
                                 Product.sku.contains(search, autoescape=True),
                                 Product.barcode.contains(search, autoescape=True)))
    total = db.session.execute(select(db.func.count()).select_from(query.subquery())\
                              .execution_options(skip_branch_scope=True)).scalar_one()
    if report and total > size:
        raise AuditError("التقرير يتجاوز 20,000 سجل؛ حدد الفترة أو الصنف ثم أعد التصدير، لا تُحذف أي حركات.")
    rows = db.session.execute(query.order_by(evidence.c.created_at.desc(), evidence.c.record_kind,\
                                             evidence.c.record_id.desc()).offset((page - 1) * size).limit(size)).mappings().all()
    ids = [row["record_id"] for row in rows if row["record_kind"] == "movement"]
    audits = {}
    if ids:
        for entry in Audit.query.execution_options(skip_branch_scope=True).filter(\
                Audit.movement_id.in_(ids), Audit.branch_id.in_(allowed)).order_by(Audit.id).all():
            audits.setdefault(entry.movement_id, []).append(entry)
    captures = {row.id: row for row in Audit.query.execution_options(skip_branch_scope=True).filter(\
        Audit.id.in_([r["record_id"] for r in rows if r["record_kind"] == "capture"]),
        Audit.branch_id.in_(allowed)).all()}
    movement_rows = {row.id: row for row in Movement.query.execution_options(skip_branch_scope=True).filter(\
        Movement.id.in_(ids), Movement.branch_id.in_(allowed)).all()}
    cost = employee_can(user, "inventory.audit.cost") or employee_can(user, "view_financial")
    sources = _sources(rows, user, allowed, tables)
    items = []
    for row in rows:
        movement = movement_rows.get(row["record_id"]) if row["record_kind"] == "movement" else None
        proofs = audits.get(row["record_id"], []) if movement else [captures.get(row["record_id"])]
        proofs = [entry for entry in proofs if entry and entry.product_id == row["product_id"]]
        details = _details(movement.details_json) if movement else {}
        variant = details.get("variant_color")
        variant = variant if isinstance(variant, str) else ""
        proof = proofs[-1] if len(proofs) == 1 else None
        delta = row["quantity"] * (1 if row["direction"] == "in" else -1)
        if proof and (proof.delta_quantity != delta or proof.before_quantity + delta != proof.after_quantity):
            proof = None
        before, after, basis = None, None, "unknown"
        if proof and not variant:
            before, after, basis = proof.before_quantity, proof.after_quantity, "product"
        if variant and movement and movement.source_type == "inventory_count":
            before, after = details.get("expected"), details.get("counted")
            if type(before) is int and type(after) is int:
                basis = "option"
            else:
                before = after = None
        source_id = row["source_id"]
        document = sources.get((row["source_type"], source_id))
        can_open = document is not None
        if row["source_type"] in ("invoice", "purchase", "inventory_count", "stock_transfer", "inventory_writeoff", "trade_in_receipt", "trade_in_reversal") and not can_open:
            source_id = None
        item = {"id": row["record_id"] * (1 if row["record_kind"] == "movement" else -1), "record_kind": row["record_kind"],
                "product_id": row["product_id"], "product_name": row["product_name"], "sku": row["sku"] or "",
                "branch_id": row["branch_id"], "branch_name": row["branch_name"],
                "created_at": row["created_at"].isoformat() + "Z", "operation": row["operation"],
                "operation_label": SOURCES[row["source_type"]] if row["source_type"] in ("trade_in_receipt", "trade_in_reversal") else LABELS.get(row["operation"], SOURCES.get(row["source_type"], "حركة مخزون")),
                "direction": row["direction"], "quantity": row["quantity"], "variant": variant,
                "before": before, "after": after, "balance_basis": basis,
                "actor_name": next(iter({a.employee_name for a in proofs if a.employee_name}), None)
                    if len({a.employee_name for a in proofs if a.employee_name}) <= 1 else None,
                "reason": (proof.reason or "") if proof else str(details.get("reason") or ""),
                "source_type": row["source_type"], "source_id": source_id, "can_open_source": can_open and bool(source_id),
                "document_kind": document[0] if document else None, "document_id": document[1] if document else None,
                "reversal": bool(movement and movement.reversal_of_key)}
        if cost:
            known = not (movement and movement.movement_type == "unclassified_adjustment" and
                details.get("auto_captured") is True and row["unit_cost"] == row["total_cost"] == 0 and
                not any(type(entry.get_metadata().get("unit_cost")) is int for entry in proofs))
            item.update(unit_cost=_cost(row["unit_cost"]) if known else None,
                        total_cost=_cost(row["total_cost"]) if known else None)
        items.append(item)
    branches = db.session.execute(select(Branch.id, Branch.name).where(Branch.id.in_(allowed))\
                                  .order_by(Branch.name).execution_options(skip_branch_scope=True)).all()
    return {"available": True, "items": items, "total": total, "page": page, "page_size": size,
            "branches": [{"id": row.id, "name": row.name} for row in branches], "can_view_cost": cost,
            "notice": "يعرض الحركات المسجلة وتغييرات الكمية الملتقطة. الرصيد القديم أو المتغير غير الموثق يظهر —؛ لا يُحسب بالتخمين."}


@desktop_api_bp.get("/inventory-activity")
def inventory_activity():
    try:
        user = actor()
        if not employee_can(user, "can_manage_inventory"):
            raise AuditError("تحتاج صلاحية عرض المخزون", "forbidden", 403)
        return jsonify(success=True, data=_list(user))
    except AuditError as error:
        db.session.rollback()
        return jsonify(success=False, error=str(error), code=error.code), error.status


def _report():
    user = actor()
    if not employee_can(user, "can_manage_inventory"):
        raise AuditError("تحتاج صلاحية عرض المخزون", "forbidden", 403)
    data = _list(user, report=True)
    if not data["available"]:
        raise AuditError("سجل الحركة غير مهيأ؛ لا يوجد تقرير مؤكد للطباعة", "unavailable", 409)
    for row in data["items"]:
        row["local_time"] = format_timestamp(row["created_at"])
    return user, data


def _cell(value):
    if isinstance(value, int) and abs(value) >= 1000000000000000:
        return "'" + str(value)
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.isdecimal()):
        return "'" + value
    return "—" if value is None else value


@desktop_api_bp.get("/inventory-activity/export")
def inventory_activity_export():
    try:
        _, data = _report()
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        headers = ["التاريخ", "الصنف", "SKU", "الفرع", "اللون / المقاس", "الحركة", "دخول / خروج", "الكمية",
                   "قبل", "بعد", "المنفذ", "المستند", "السبب"]
        if data["can_view_cost"]:
            headers += ["تكلفة الوحدة", "قيمة الحركة بالتكلفة"]
        writer.writerow(headers)
        for row in data["items"]:
            values = [row["local_time"], row["product_name"], row["sku"], row["branch_name"], row["variant"],
                      row["operation_label"], "دخول" if row["direction"] == "in" else "خروج", row["quantity"],
                      row["before"], row["after"], row["actor_name"], row["source_id"], row["reason"]]
            if data["can_view_cost"]:
                values += [row["unit_cost"], row["total_cost"]]
            writer.writerow([_cell(value) for value in values])
        return jsonify(success=True, data={"content": "\ufeff" + buffer.getvalue(), "filename": "finora-inventory-movements.csv"})
    except AuditError as error:
        db.session.rollback()
        return jsonify(success=False, error=str(error), code=error.code), error.status


@desktop_api_bp.get("/inventory-activity/print")
def inventory_activity_print():
    try:
        user, data = _report()
        return render_template("inventory_activity_print.html", data=data, actor=user.name,
                               filters={key: request.args.get(key, "") for key in ("q", "from", "to")})
    except AuditError as error:
        db.session.rollback()
        return jsonify(success=False, error=str(error), code=error.code), error.status
