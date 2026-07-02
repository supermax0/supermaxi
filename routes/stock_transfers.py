"""Inter-branch stock transfer routes."""
import json
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.branch import Branch, StockTransfer, StockTransferLine
from models.product import Product
from utils.activity_logger import log_mutation
from utils.branch_context import init_branch_context
from utils.branch_migration import ensure_branch_schema
from utils.branch_stock_service import BranchStockError, branch_stock_map, get_branch_stock, transfer_deduct, transfer_receive
from utils.permission_checks import check_permission, get_current_employee, guard_permission

stock_transfers_bp = Blueprint("stock_transfers", __name__, url_prefix="/inventory/transfers")

TRANSFER_STATUS_LABELS = {
    "draft": "مسودة",
    "sent": "قيد النقل",
    "received": "مستلم",
    "cancelled": "ملغي",
}


@stock_transfers_bp.before_request
def _transfer_guard():
    if "user_id" not in session:
        return redirect("/login")
    denied = guard_permission("manage_inventory")
    if denied:
        return denied
    ensure_branch_schema()
    init_branch_context()
    return None


def _is_admin() -> bool:
    if session.get("role") == "admin":
        return True
    employee = get_current_employee()
    return bool(employee and employee.role == "admin")


def _status_label(status: str) -> str:
    return TRANSFER_STATUS_LABELS.get(status or "", status or "—")


def _next_transfer_no() -> str:
    last = StockTransfer.query.order_by(StockTransfer.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"TR{n:05d}"


def _products_catalog(products: list[Product]) -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku or "",
            "barcode": p.barcode or "",
            "buy_price": int(p.buy_price or 0),
            "sale_price": int(p.sale_price or 0),
        }
        for p in products
    ]


def _branch_stocks_json(branches: list[Branch]) -> dict[str, dict[int, int]]:
    return {str(b.id): branch_stock_map(b.id) for b in branches}


def _line_row(product: Product | None, line: StockTransferLine, from_branch_id: int) -> dict:
    buy_price = int(product.buy_price or 0) if product else 0
    sale_price = int(product.sale_price or 0) if product else 0
    qty = int(line.quantity or 0)
    return {
        "product_id": line.product_id,
        "product_name": product.name if product else f"#{line.product_id}",
        "sku": (product.sku or "") if product else "",
        "barcode": (product.barcode or "") if product else "",
        "buy_price": buy_price,
        "sale_price": sale_price,
        "quantity": qty,
        "quantity_received": line.quantity_received,
        "line_cost": buy_price * qty,
        "available": get_branch_stock(from_branch_id, line.product_id),
    }


def _transfer_lines_payload(transfer: StockTransfer) -> list[dict]:
    rows = []
    for line in transfer.lines:
        product = Product.query.get(line.product_id)
        rows.append(_line_row(product, line, transfer.from_branch_id))
    return rows


def _transfer_totals(lines: list[dict]) -> dict:
    return {
        "items_count": len(lines),
        "total_qty": sum(int(row.get("quantity") or 0) for row in lines),
        "total_cost": sum(int(row.get("line_cost") or 0) for row in lines),
    }


def _form_context(**extra):
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    base = {
        "branches": branches,
        "products": products,
        "products_json": json.dumps(_products_catalog(products), ensure_ascii=False),
        "branch_stocks_json": json.dumps(_branch_stocks_json(branches), ensure_ascii=False),
        "is_admin": _is_admin(),
        "status_labels": TRANSFER_STATUS_LABELS,
    }
    base.update(extra)
    return base


@stock_transfers_bp.route("/", methods=["GET"])
def transfers_index():
    transfers = StockTransfer.query.order_by(StockTransfer.created_at.desc()).limit(300).all()
    return render_template(
        "inventory_transfers.html",
        transfers=transfers,
        status_labels=TRANSFER_STATUS_LABELS,
    )


@stock_transfers_bp.route("/new", methods=["GET", "POST"])
def transfers_new():
    if request.method == "GET":
        return render_template(
            "inventory_transfer_form.html",
            transfer=None,
            lines=[],
            readonly=False,
            **_form_context(),
        )

    from_branch_id = int(request.form.get("from_branch_id") or 0)
    to_branch_id = int(request.form.get("to_branch_id") or 0)
    note = (request.form.get("note") or "").strip() or None

    if from_branch_id <= 0 or to_branch_id <= 0 or from_branch_id == to_branch_id:
        flash("اختر فرع مصدر وفرع وجهة مختلفين.", "error")
        return redirect(url_for("stock_transfers.transfers_new"))

    product_ids = request.form.getlist("product_id")
    quantities = request.form.getlist("quantity")
    parsed_lines: list[tuple[int, int]] = []
    for pid_raw, qty_raw in zip(product_ids, quantities):
        pid = int(pid_raw or 0)
        qty = int(qty_raw or 0)
        if pid > 0 and qty > 0:
            parsed_lines.append((pid, qty))
    if not parsed_lines:
        flash("أضف منتجاً واحداً على الأقل.", "error")
        return redirect(url_for("stock_transfers.transfers_new"))

    transfer = StockTransfer(
        transfer_no=_next_transfer_no(),
        from_branch_id=from_branch_id,
        to_branch_id=to_branch_id,
        status="draft",
        note=note,
        created_by_id=session.get("user_id"),
    )
    db.session.add(transfer)
    db.session.flush()

    for product_id, qty in parsed_lines:
        db.session.add(
            StockTransferLine(
                transfer_id=transfer.id,
                product_id=product_id,
                quantity=qty,
            )
        )

    db.session.commit()
    log_mutation(
        "create",
        "transfer",
        "stock_transfer",
        transfer.id,
        None,
        transfer.to_dict(),
        f"إنشاء نقل مخزون {transfer.transfer_no}",
    )
    flash("تم حفظ طلب النقل كمسودة.", "success")
    return redirect(url_for("stock_transfers.transfers_view", transfer_id=transfer.id))


@stock_transfers_bp.route("/<int:transfer_id>", methods=["GET"])
def transfers_view(transfer_id):
    transfer = StockTransfer.query.get_or_404(transfer_id)
    lines = _transfer_lines_payload(transfer)
    return render_template(
        "inventory_transfer_form.html",
        transfer=transfer,
        lines=lines,
        totals=_transfer_totals(lines),
        readonly=True,
        **_form_context(),
    )


@stock_transfers_bp.route("/<int:transfer_id>/print", methods=["GET"])
def transfers_print(transfer_id):
    transfer = StockTransfer.query.get_or_404(transfer_id)
    lines = _transfer_lines_payload(transfer)
    return render_template(
        "inventory_transfer_print.html",
        transfer=transfer,
        lines=lines,
        totals=_transfer_totals(lines),
        status_label=_status_label(transfer.status),
    )


@stock_transfers_bp.route("/<int:transfer_id>/send", methods=["POST"])
def transfers_send(transfer_id):
    if not check_permission("manage_inventory"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    if not _is_admin():
        return jsonify({"ok": False, "error": "هذا الإجراء متاح للمدير فقط"}), 403
    transfer = StockTransfer.query.get_or_404(transfer_id)
    if transfer.status != "draft":
        return jsonify({"ok": False, "error": "لا يمكن ترحيل هذا النقل"}), 400
    lines = [(line.product_id, line.quantity) for line in transfer.lines]
    try:
        transfer_deduct(transfer.from_branch_id, lines)
        transfer.status = "sent"
        transfer.sent_at = datetime.utcnow()
        db.session.commit()
    except BranchStockError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_mutation(
        "send",
        "transfer",
        "stock_transfer",
        transfer.id,
        {"status": "draft"},
        {"status": "sent"},
        f"تجهيز وترحيل مخزون {transfer.transfer_no}",
    )
    return jsonify({"ok": True})


@stock_transfers_bp.route("/<int:transfer_id>/receive", methods=["POST"])
def transfers_receive(transfer_id):
    if not check_permission("manage_inventory"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    transfer = StockTransfer.query.get_or_404(transfer_id)
    if transfer.status != "sent":
        return jsonify({"ok": False, "error": "النقل غير جاهز للاستلام"}), 400
    lines = [(line.product_id, line.quantity) for line in transfer.lines]
    try:
        transfer_receive(transfer.to_branch_id, lines)
        for line in transfer.lines:
            line.quantity_received = line.quantity
        transfer.status = "received"
        transfer.received_at = datetime.utcnow()
        transfer.received_by_id = session.get("user_id")
        db.session.commit()
    except BranchStockError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_mutation(
        "receive",
        "transfer",
        "stock_transfer",
        transfer.id,
        {"status": "sent"},
        {"status": "received"},
        f"استلام نقل مخزون {transfer.transfer_no}",
    )
    return jsonify({"ok": True})


@stock_transfers_bp.route("/<int:transfer_id>/cancel", methods=["POST"])
def transfers_cancel(transfer_id):
    if not check_permission("manage_inventory"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    transfer = StockTransfer.query.get_or_404(transfer_id)
    if transfer.status == "received":
        return jsonify({"ok": False, "error": "لا يمكن إلغاء نقل مستلم"}), 400
    prev = transfer.status
    if transfer.status == "sent":
        lines = [(line.product_id, line.quantity) for line in transfer.lines]
        try:
            transfer_receive(transfer.from_branch_id, lines)
        except BranchStockError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
    transfer.status = "cancelled"
    db.session.commit()
    log_mutation(
        "cancel",
        "transfer",
        "stock_transfer",
        transfer.id,
        {"status": prev},
        {"status": "cancelled"},
        f"إلغاء نقل مخزون {transfer.transfer_no}",
    )
    return jsonify({"ok": True})
