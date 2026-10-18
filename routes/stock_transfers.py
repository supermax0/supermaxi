"""Inter-branch stock transfer routes."""
import json
from datetime import datetime

from flask import Blueprint, abort, flash, has_app_context, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.branch import Branch, StockTransfer, StockTransferLine
from models.product import Product
from models.product_color_variant import ProductColorVariant
from utils.activity_logger import log_mutation
from utils.branch_context import init_branch_context
from utils.branch_migration import ensure_branch_schema
from utils.branch_stock_service import (
    BranchStockError,
    branch_stock_map,
    deduct_stock,
    get_branch_stock,
    receive_stock,
)
from utils.permission_checks import check_permission, get_current_employee, guard_permission
from utils.branch_scope import active_branch_id, is_general_admin, viewing_all_branches
from utils.branch_mode import independent_branches_enabled
from utils.branch_product_service import product_for_branch
from utils.product_color_service import (
    ProductColorError,
    colors_for_product_dict,
    deduct_color_stock,
    product_has_colors,
    receive_color_stock,
)
from utils.stock_movement_guard import StockMovementConflict, claim_stock_movement

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


def _require_transfer_access(transfer: StockTransfer) -> StockTransfer:
    if is_general_admin():
        return transfer
    branch_id = int(active_branch_id() or 0)
    if branch_id and branch_id in {int(transfer.from_branch_id), int(transfer.to_branch_id)}:
        return transfer
    abort(404)


def _next_transfer_no() -> str:
    last = StockTransfer.query.order_by(StockTransfer.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"TR{n:05d}"


def _normalize_variant_color(raw: str | None) -> str | None:
    color = (raw or "").strip()
    return color or None


def _transfer_catalog_key(product: Product) -> str:
    group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
    if group_id:
        return f"group:{group_id}"
    barcode = str(getattr(product, "barcode", "") or "").strip()
    if barcode:
        return f"barcode:{barcode}"
    sku = str(getattr(product, "sku", "") or "").strip()
    return f"sku:{sku}" if sku else f"product:{getattr(product, 'id', '')}"


def _branch_color_stock_catalog(products: list[Product]) -> dict[int, dict[str, dict[str, int]]]:
    if not products or not has_app_context():
        return {}
    product_by_id = {int(p.id): p for p in products if getattr(p, "id", None)}
    family_members: dict[str, list[Product]] = {}
    for product in product_by_id.values():
        family_members.setdefault(_transfer_catalog_key(product), []).append(product)
    branch_colors_by_key: dict[str, dict[str, dict[str, int]]] = {}
    rows = (
        ProductColorVariant.query
        .filter(ProductColorVariant.product_id.in_(list(product_by_id)))
        .all()
    )
    for variant in rows:
        product = product_by_id.get(int(variant.product_id))
        if product is None or not getattr(product, "branch_id", None):
            continue
        key = _transfer_catalog_key(product)
        branch_key = str(int(product.branch_id))
        color = _normalize_variant_color(variant.color_name)
        if not color:
            continue
        branch_colors = branch_colors_by_key.setdefault(key, {}).setdefault(branch_key, {})
        branch_colors[color] = branch_colors.get(color, 0) + int(variant.quantity or 0)

    result: dict[int, dict[str, dict[str, int]]] = {}
    for key, members in family_members.items():
        branch_colors = branch_colors_by_key.get(key, {})
        for member in members:
            result[int(member.id)] = branch_colors
    return result


def _products_catalog(products: list[Product]) -> list[dict]:
    catalog = []
    branch_color_stocks = _branch_color_stock_catalog(products)
    for p in products:
        row = {
            "id": p.id,
            "branch_id": p.branch_id,
            "catalog_group_id": getattr(p, "catalog_group_id", "") or "",
            "name": p.name,
            "sku": p.sku or "",
            "barcode": p.barcode or "",
            "buy_price": int(p.buy_price or 0),
            "sale_price": int(p.sale_price or 0),
            "branch_color_stocks": branch_color_stocks.get(int(p.id), {}),
        }
        row.update(colors_for_product_dict(p))
        catalog.append(row)
    return catalog


def _branch_stocks_json(branches: list[Branch]) -> dict[str, dict[int, int]]:
    # The shared branch mode is a company-wide view: stock held in another
    # physical branch must remain visible in the transfer screen as well.
    # A general admin can choose any source branch on this form, so preload
    # stock for every branch even if the global dashboard filter is focused
    # on a single branch.  Staff remain limited to their active branch.
    visible_id = None if (
        is_general_admin()
        or viewing_all_branches()
        or not independent_branches_enabled()
    ) else int(active_branch_id() or 0)
    return {
        str(branch.id): (branch_stock_map(branch.id) if visible_id is None or branch.id == visible_id else {})
        for branch in branches
    }


def _transferable_qty(from_branch_id: int, product_id: int, variant_color: str | None) -> int:
    from utils.branch_sales import available_fulfillment_qty

    return int(available_fulfillment_qty(int(from_branch_id), int(product_id), variant_color) or 0)


def _branch_color_product_id(branch_id: int, product_id: int, color: str | None) -> int:
    """Resolve a shared product color to the local variant row for a branch."""
    color = _normalize_variant_color(color)
    if not color or independent_branches_enabled():
        return int(product_id)
    product = Product.query.execution_options(skip_branch_scope=True).get(int(product_id))
    group_id = str(getattr(product, "catalog_group_id", "") or "").strip() if product else ""
    if not group_id:
        return int(product_id)
    local = (
        Product.query.execution_options(skip_branch_scope=True)
        .join(ProductColorVariant, ProductColorVariant.product_id == Product.id)
        .filter(
            Product.catalog_group_id == group_id,
            Product.branch_id == int(branch_id),
            ProductColorVariant.color_name == color,
        )
        .first()
    )
    return int(local.id) if local else int(product_id)


def _product_for_transfer_source(product_id: int, branch_id: int) -> Product | None:
    """Use the source branch's local copy in shared-branch mode."""
    product = (
        Product.query.execution_options(skip_branch_scope=True)
        .filter_by(id=int(product_id), active=True)
        .first()
    )
    if not product or independent_branches_enabled():
        return product
    if int(product.branch_id or 0) == int(branch_id):
        return product
    local = product_for_branch(product, branch_id, create=False)
    return local or product


def _validate_transfer_line(product: Product, qty: int, variant_color: str | None, from_branch_id: int) -> str:
    color = _normalize_variant_color(variant_color)
    if product_has_colors(product) and not color:
        return f"يجب اختيار لون للمنتج: {product.name}"
    if color and not product_has_colors(product):
        return f"المنتج «{product.name}» لا يدعم الألوان"
    available = _transferable_qty(from_branch_id, product.id, color)
    if qty > available:
        color_note = f" للون ({color})" if color else ""
        return f"الكمية المطلوبة للمنتج «{product.name}»{color_note} أكبر من المتوفر ({available})"
    return ""


def _line_row(product: Product | None, line: StockTransferLine, from_branch_id: int) -> dict:
    buy_price = int(product.buy_price or 0) if product else 0
    sale_price = int(product.sale_price or 0) if product else 0
    qty = int(line.quantity or 0)
    color = _normalize_variant_color(getattr(line, "variant_color", None))
    product_name = product.name if product else f"#{line.product_id}"
    return {
        "product_id": line.product_id,
        "product_name": product_name,
        "variant_color": color or "",
        "display_name": f"{product_name} — {color}" if color else product_name,
        "sku": (product.sku or "") if product else "",
        "barcode": (product.barcode or "") if product else "",
        "buy_price": buy_price,
        "sale_price": sale_price,
        "quantity": qty,
        "quantity_received": line.quantity_received,
        "line_cost": buy_price * qty,
        "available": _transferable_qty(from_branch_id, line.product_id, color),
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


def _apply_transfer_movements(transfer: StockTransfer, phase: str) -> None:
    if phase == "send":
        direction = "out"
        branch_id = transfer.from_branch_id
        movement_type = "transfer_send"
    elif phase == "receive":
        direction = "in"
        branch_id = transfer.to_branch_id
        movement_type = "transfer_receive"
    elif phase == "cancel":
        direction = "in"
        branch_id = transfer.from_branch_id
        movement_type = "transfer_cancel"
    else:
        raise ValueError("مرحلة نقل المخزون غير صالحة")

    for line in transfer.lines:
        product_query = Product.query
        if hasattr(product_query, "execution_options"):
            product_query = product_query.execution_options(skip_branch_scope=True)
        if hasattr(product_query, "filter_by"):
            product = product_query.filter_by(id=line.product_id).first()
        else:
            product = product_query.get(line.product_id)
        color = _normalize_variant_color(getattr(line, "variant_color", None))
        real_valuation = has_app_context() and product is not None and hasattr(product, "_sa_instance_state")
        cost_layers = []
        if real_valuation:
            from utils.inventory_transfer_valuation import layers as recorded_layers
            cost_layers = recorded_layers(transfer.id, line.id, phase)
        if phase == "send" and product is not None and not cost_layers:
            err = _validate_transfer_line(product, int(line.quantity or 0), color, transfer.from_branch_id)
            if err:
                raise BranchStockError(err)
        send_key = f"transfer:{transfer.id}:line:{line.id}:send"
        movement_key = f"transfer:{transfer.id}:line:{line.id}:{phase}"
        movement_product = product
        if phase == "receive" and product is not None:
            # Real persisted products always carry catalog_group_id.  Keeping
            # the fallback makes legacy/lightweight import rows transferable
            # without crashing before their catalog migration runs.
            if hasattr(product, "catalog_group_id"):
                movement_product = product_for_branch(product, transfer.to_branch_id)
                line.destination_product_id = movement_product.id
        movement_product_id = movement_product.id if movement_product is not None else line.product_id
        if real_valuation and not cost_layers:
            from utils.inventory_transfer_valuation import apply as carry_valuation
            cost_layers = carry_valuation(transfer, line, phase, product, movement_product)
        movement_details = {
            "from_branch_id": transfer.from_branch_id,
            "to_branch_id": transfer.to_branch_id,
            "variant_color": color,
        }
        if real_valuation:
            movement_details.update(valuation_layers=[{"lot_id": row.lot_id, "quantity": row.quantity,
                "unit_cost": row.unit_cost} for row in cost_layers], in_transit=phase == "send")
        exact_cost = sum(row.quantity * row.unit_cost for row in cost_layers) if real_valuation else None
        if exact_cost is not None and exact_cost>9223372036854775807:
            raise ValueError("كلفة التحويل تتجاوز المجال المسموح؛ راجع الكمية")
        claim = claim_stock_movement(
            movement_key,
            movement_type=movement_type,
            direction=direction,
            product_id=movement_product_id,
            branch_id=branch_id,
            quantity=int(line.quantity or 0),
            unit_cost=exact_cost // int(line.quantity) if exact_cost is not None else int(getattr(product, "buy_price", 0) or 0),
            source_type="stock_transfer",
            source_id=transfer.id,
            source_line_id=line.id,
            reversal_of_key=send_key if phase == "cancel" else None,
            details=movement_details,
        )
        if not claim.applied:
            continue
        if exact_cost is not None:
            claim.movement.total_cost = exact_cost
        if direction == "out":
            deduct_stock(branch_id, line.product_id, line.quantity)
            if color and hasattr(product, "catalog_group_id"):
                source_color_product_id = _branch_color_product_id(
                    transfer.from_branch_id, line.product_id, color
                )
                deduct_color_stock(
                    source_color_product_id,
                    color,
                    line.quantity,
                    branch_id=transfer.from_branch_id,
                )
        else:
            receive_stock(branch_id, movement_product_id, line.quantity)
            if color and hasattr(movement_product, "catalog_group_id"):
                destination_color_product_id = _branch_color_product_id(
                    transfer.to_branch_id, movement_product_id, color
                )
                receive_color_stock(
                    destination_color_product_id,
                    color,
                    line.quantity,
                    branch_id=transfer.to_branch_id,
                )
            if movement_product is not None and hasattr(movement_product, "catalog_group_id"):
                movement_product.quantity = get_branch_stock(branch_id, movement_product_id)


def _form_context(**extra):
    # Branches are company-level records.  Keep this query independent from
    # the active branch scope: a transfer always needs to see both the source
    # and destination branch, even when the user is currently viewing one
    # branch only.
    branches = (
        Branch.query.execution_options(skip_branch_scope=True)
        .filter_by(is_active=True)
        .order_by(Branch.name)
        .all()
    )
    products = (
        Product.query.execution_options(skip_branch_scope=True)
        .filter_by(active=True)
        .order_by(Product.name)
        .all()
    )
    base = {
        "branches": branches,
        "products": products,
        "products_json": json.dumps(_products_catalog(products), ensure_ascii=False),
        "branch_stocks_json": json.dumps(_branch_stocks_json(branches), ensure_ascii=False),
        "independent_branches_enabled": independent_branches_enabled(),
        "is_admin": _is_admin(),
        "status_labels": TRANSFER_STATUS_LABELS,
    }
    base.update(extra)
    return base


@stock_transfers_bp.route("/", methods=["GET"])
def transfers_index():
    query = StockTransfer.query
    if not is_general_admin():
        branch_id = int(active_branch_id() or 0)
        query = query.filter(db.or_(
            StockTransfer.from_branch_id == branch_id,
            StockTransfer.to_branch_id == branch_id,
        ))
    transfers = query.order_by(StockTransfer.created_at.desc()).limit(300).all()
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
    if not is_general_admin() and int(active_branch_id() or 0) != from_branch_id:
        flash("يمكنك إرسال المخزون من فرعك فقط.", "error")
        return redirect(url_for("stock_transfers.transfers_new"))

    product_ids = request.form.getlist("product_id")
    quantities = request.form.getlist("quantity")
    colors = request.form.getlist("variant_color")
    parsed_lines: list[tuple[int, int, str | None]] = []
    seen_keys: set[tuple[int, str]] = set()
    for idx, (pid_raw, qty_raw) in enumerate(zip(product_ids, quantities)):
        pid = int(pid_raw or 0)
        qty = int(qty_raw or 0)
        color = _normalize_variant_color(colors[idx] if idx < len(colors) else None)
        if pid <= 0 or qty <= 0:
            continue
        product = _product_for_transfer_source(pid, from_branch_id)
        if not product:
            flash(f"منتج غير موجود: #{pid}", "error")
            return redirect(url_for("stock_transfers.transfers_new"))
        if independent_branches_enabled() and int(product.branch_id or 0) != from_branch_id:
            flash(f"المنتج «{product.name}» غير موجود في فرع المصدر.", "error")
            return redirect(url_for("stock_transfers.transfers_new"))
        err = _validate_transfer_line(product, qty, color, from_branch_id)
        if err:
            flash(err, "error")
            return redirect(url_for("stock_transfers.transfers_new"))
        key = (pid, color or "")
        if key in seen_keys:
            flash(
                f"تكرار لنفس المنتج واللون: {product.name}" + (f" — {color}" if color else ""),
                "error",
            )
            return redirect(url_for("stock_transfers.transfers_new"))
        seen_keys.add(key)
        parsed_lines.append((pid, qty, color))
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

    for product_id, qty, color in parsed_lines:
        db.session.add(
            StockTransferLine(
                transfer_id=transfer.id,
                product_id=product_id,
                variant_color=color,
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


@stock_transfers_bp.route("/quick", methods=["POST"])
def transfers_quick():
    """Create, send and receive one small transfer from the shortage dialog."""
    if not check_permission("manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    if not _is_admin():
        return jsonify({
            "success": False,
            "error": "النقل والاستلام الفوري متاح للمدير فقط",
        }), 403

    data = request.get_json(silent=True) or {}
    try:
        from_branch_id = int(data.get("from_branch_id") or 0)
        to_branch_id = int(data.get("to_branch_id") or 0)
        product_id = int(data.get("product_id") or 0)
        quantity = int(data.get("quantity") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "بيانات النقل غير صالحة"}), 400

    if from_branch_id <= 0 or to_branch_id <= 0 or from_branch_id == to_branch_id:
        return jsonify({"success": False, "error": "اختر فرع مصدر وفرع وجهة مختلفين"}), 400
    if product_id <= 0 or quantity <= 0:
        return jsonify({"success": False, "error": "المنتج والكمية مطلوبان"}), 400

    source = Branch.query.filter_by(id=from_branch_id, is_active=True).first()
    destination = Branch.query.filter_by(id=to_branch_id, is_active=True).first()
    product = _product_for_transfer_source(product_id, from_branch_id)
    if not source or not destination:
        return jsonify({"success": False, "error": "أحد الفروع غير موجود أو غير نشط"}), 404
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود أو غير نشط"}), 404
    if independent_branches_enabled() and int(product.branch_id or 0) != from_branch_id:
        return jsonify({"success": False, "error": "المنتج غير موجود في فرع المصدر"}), 400

    color = _normalize_variant_color(data.get("variant_color"))
    validation_error = _validate_transfer_line(product, quantity, color, from_branch_id)
    if validation_error:
        return jsonify({"success": False, "error": validation_error}), 400

    transfer = StockTransfer(
        transfer_no=_next_transfer_no(),
        from_branch_id=from_branch_id,
        to_branch_id=to_branch_id,
        status="draft",
        note=(data.get("note") or "معالجة سريعة لنقص مخزون كشف المندوب").strip(),
        created_by_id=session.get("user_id"),
    )
    db.session.add(transfer)
    db.session.flush()
    line = StockTransferLine(
        transfer_id=transfer.id,
        product_id=int(product.id),
        variant_color=color,
        quantity=quantity,
    )
    db.session.add(line)
    db.session.flush()

    try:
        from utils.stock_transfer_state import transition
        transition(transfer, {"draft"}, "sent")
        _apply_transfer_movements(transfer, "send")
        transfer.status = "sent"
        transfer.sent_at = datetime.utcnow()
        _apply_transfer_movements(transfer, "receive")
        line.quantity_received = quantity
        transfer.status = "received"
        transfer.received_at = datetime.utcnow()
        transfer.received_by_id = session.get("user_id")
        db.session.commit()
    except (BranchStockError, ProductColorError, StockMovementConflict, ValueError) as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc) or "تعذر إكمال النقل"}), 500

    try:
        log_mutation(
            "quick_transfer",
            "transfer",
            "stock_transfer",
            transfer.id,
            None,
            transfer.to_dict(),
            f"نقل واستلام فوري {transfer.transfer_no} لمعالجة نقص المخزون",
        )
    except Exception:
        pass
    return jsonify({
        "success": True,
        "message": f"تم نقل {quantity} من {source.name} إلى {destination.name}",
        "transfer_id": transfer.id,
        "transfer_no": transfer.transfer_no,
    })


@stock_transfers_bp.route("/<int:transfer_id>", methods=["GET"])
def transfers_view(transfer_id):
    transfer = _require_transfer_access(StockTransfer.query.get_or_404(transfer_id))
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
    transfer = _require_transfer_access(StockTransfer.query.get_or_404(transfer_id))
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
    transfer = _require_transfer_access(StockTransfer.query.get_or_404(transfer_id))
    if transfer.status != "draft":
        return jsonify({"ok": False, "error": "لا يمكن ترحيل هذا النقل"}), 400
    try:
        _apply_transfer_movements(transfer, "send")
        transfer.status = "sent"
        transfer.sent_at = datetime.utcnow()
        db.session.commit()
    except (BranchStockError, ProductColorError, StockMovementConflict, ValueError) as exc:
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
    transfer = _require_transfer_access(StockTransfer.query.get_or_404(transfer_id))
    if transfer.status != "sent":
        return jsonify({"ok": False, "error": "النقل غير جاهز للاستلام"}), 400
    try:
        from utils.stock_transfer_state import transition
        transition(transfer, {"sent"}, "received")
        _apply_transfer_movements(transfer, "receive")
        for line in transfer.lines:
            line.quantity_received = line.quantity
        transfer.status = "received"
        transfer.received_at = datetime.utcnow()
        transfer.received_by_id = session.get("user_id")
        db.session.commit()
    except (BranchStockError, ProductColorError, StockMovementConflict, ValueError) as exc:
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
    transfer = _require_transfer_access(StockTransfer.query.get_or_404(transfer_id))
    if transfer.status == "received":
        return jsonify({"ok": False, "error": "لا يمكن إلغاء نقل مستلم"}), 400
    prev = transfer.status
    try:
        from utils.stock_transfer_state import transition
        transition(transfer, {"draft", "sent"}, "cancelled")
        if prev == "sent":
            _apply_transfer_movements(transfer, "cancel")
    except (BranchStockError, ProductColorError, StockMovementConflict, ValueError) as exc:
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
