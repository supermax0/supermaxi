"""Inter-branch stock transfer routes."""
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.branch import Branch, StockTransfer, StockTransferLine
from models.product import Product
from utils.activity_logger import log_mutation
from utils.branch_context import current_branch_id, init_branch_context
from utils.branch_migration import ensure_branch_schema
from utils.branch_stock_service import BranchStockError, get_branch_stock, transfer_deduct, transfer_receive
from utils.permission_checks import check_permission, guard_permission

stock_transfers_bp = Blueprint("stock_transfers", __name__, url_prefix="/inventory/transfers")


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


def _next_transfer_no() -> str:
    last = StockTransfer.query.order_by(StockTransfer.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"TR{n:05d}"


def _transfer_lines_payload(transfer: StockTransfer) -> list[dict]:
    rows = []
    for line in transfer.lines:
        product = Product.query.get(line.product_id)
        rows.append(
            {
                "product_id": line.product_id,
                "product_name": product.name if product else f"#{line.product_id}",
                "quantity": line.quantity,
                "quantity_received": line.quantity_received,
                "available": get_branch_stock(transfer.from_branch_id, line.product_id),
            }
        )
    return rows


@stock_transfers_bp.route("/", methods=["GET"])
def transfers_index():
    transfers = StockTransfer.query.order_by(StockTransfer.created_at.desc()).limit(300).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    return render_template(
        "inventory_transfers.html",
        transfers=transfers,
        branches=branches,
    )


@stock_transfers_bp.route("/new", methods=["GET", "POST"])
def transfers_new():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()

    if request.method == "GET":
        return render_template(
            "inventory_transfer_form.html",
            transfer=None,
            branches=branches,
            products=products,
            lines=[],
        )

    from_branch_id = int(request.form.get("from_branch_id") or 0)
    to_branch_id = int(request.form.get("to_branch_id") or 0)
    note = (request.form.get("note") or "").strip() or None
    action = (request.form.get("action") or "draft").strip()

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

    if action == "send":
        try:
            transfer_deduct(from_branch_id, parsed_lines)
            transfer.status = "sent"
            transfer.sent_at = datetime.utcnow()
        except BranchStockError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("stock_transfers.transfers_new"))

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
    flash("تم حفظ طلب النقل.", "success")
    return redirect(url_for("stock_transfers.transfers_index"))


@stock_transfers_bp.route("/<int:transfer_id>", methods=["GET"])
def transfers_view(transfer_id):
    transfer = StockTransfer.query.get_or_404(transfer_id)
    return render_template(
        "inventory_transfer_form.html",
        transfer=transfer,
        branches=Branch.query.filter_by(is_active=True).order_by(Branch.name).all(),
        products=Product.query.filter_by(active=True).order_by(Product.name).all(),
        lines=_transfer_lines_payload(transfer),
        readonly=True,
    )


@stock_transfers_bp.route("/<int:transfer_id>/send", methods=["POST"])
def transfers_send(transfer_id):
    if not check_permission("manage_inventory"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    transfer = StockTransfer.query.get_or_404(transfer_id)
    if transfer.status != "draft":
        return jsonify({"ok": False, "error": "لا يمكن إرسال هذا النقل"}), 400
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
        f"إرسال نقل مخزون {transfer.transfer_no}",
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
