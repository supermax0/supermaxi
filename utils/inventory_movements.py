"""
حساب حركات المخزون (Inventory Movements Calculator)
هذا الملف يحتوي على دوال لحساب سجل حركات المخزون
للعرض فقط - لا يغيّر أي بيانات

القواعد:
1. كل حركة مخزون مرتبطة بسبب واضح
2. المخزون يُحسب بالتكلفة دائماً
3. السجل للعرض فقط
"""

from datetime import datetime, date
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.order_item import OrderItem
from models.invoice import Invoice
from extensions import db
from utils.order_status import is_canceled, is_returned


def get_product_inventory_movements(product_id, branch_id=None):
    """
    حساب سجل حركات المخزون لمنتج محدد
    
    السبب المحاسبي:
    - سجل حركات المخزون يساعد في تتبع جميع التغييرات
    - لكل حركة سبب واضح (شراء، بيع، مرتجع، تعديل)
    - الرصيد يُحسب بالتكلفة دائماً
    
    Args:
        product_id: معرف المنتج
        
    Returns:
        list: قائمة حركات المخزون مرتبة حسب التاريخ
    """
    product = Product.query.get(product_id)
    if not product:
        return []
    
    movements = []

    if branch_id:
        from models.branch import BranchStock

        branch_stock = BranchStock.query.filter_by(
            product_id=product_id,
            branch_id=branch_id,
        ).first()
        opening_stock = int(branch_stock.opening_stock or 0) if branch_stock else 0
    else:
        try:
            from models.branch import BranchStock

            branch_opening = (
                db.session.query(db.func.coalesce(db.func.sum(BranchStock.opening_stock), 0))
                .filter(BranchStock.product_id == product_id)
                .scalar()
            )
            opening_stock = int(branch_opening or 0)
        except Exception:
            db.session.rollback()
            opening_stock = int(product.opening_stock or 0)

    current_balance = opening_stock
    
    # ==========================
    # 1. المخزون الافتتاحي
    # ==========================
    if opening_stock > 0:
        movements.append({
            "date": product.created_at.date() if product.created_at else date.today(),
            "type": "opening_stock",
            "type_ar": "مخزون افتتاحي",
            "quantity_in": opening_stock,
            "quantity_out": 0,
            "balance_after": current_balance,
            "cost_per_unit": product.buy_price,
            "total_cost": opening_stock * product.buy_price,
            "reference_type": "product",
            "reference_id": product.id,
            "description": f"مخزون افتتاحي - {product.name}"
        })
    
    # ==========================
    # 2. المشتريات (Purchases)
    # ==========================
    purchase_items_query = (
        PurchaseItem.query
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(PurchaseItem.product_id == product_id)
    )
    if branch_id:
        purchase_items_query = purchase_items_query.filter(Purchase.branch_id == branch_id)

    purchase_items = purchase_items_query.order_by(Purchase.created_at, PurchaseItem.id).all()
    purchase_ids_with_items = {item.purchase_id for item in purchase_items}

    for item in purchase_items:
        purchase = item.purchase
        status = str(getattr(purchase, "status", "") or "").strip().lower()
        if status in {"cancelled", "canceled"}:
            continue
        if status == "draft":
            continue
        qty = int(item.quantity or 0)
        unit_cost = int(item.final_unit_cost or item.unit_cost_before_discount or 0)
        current_balance += qty
        movements.append({
            "date": purchase.purchase_date if purchase.purchase_date else (purchase.created_at.date() if purchase.created_at else date.today()),
            "type": "purchase",
            "type_ar": "شراء",
            "quantity_in": qty,
            "quantity_out": 0,
            "balance_after": current_balance,
            "cost_per_unit": unit_cost,
            "total_cost": int(item.line_total or (qty * unit_cost)),
            "reference_type": "purchase",
            "reference_id": purchase.id,
            "description": f"شراء من مورد #{purchase.supplier_id if purchase.supplier_id else 'غير محدد'}"
        })

    legacy_purchases_query = Purchase.query.filter_by(product_id=product_id)
    if branch_id:
        legacy_purchases_query = legacy_purchases_query.filter(Purchase.branch_id == branch_id)
    legacy_purchases = legacy_purchases_query.order_by(Purchase.created_at).all()
    for purchase in legacy_purchases:
        if purchase.id in purchase_ids_with_items:
            continue
        status = str(getattr(purchase, "status", "") or "").strip().lower()
        if status in {"cancelled", "canceled", "draft"}:
            continue
        qty = int(purchase.quantity or 0)
        unit_cost = int(purchase.price or 0)
        current_balance += qty
        movements.append({
            "date": purchase.purchase_date if purchase.purchase_date else (purchase.created_at.date() if purchase.created_at else date.today()),
            "type": "purchase",
            "type_ar": "شراء",
            "quantity_in": qty,
            "quantity_out": 0,
            "balance_after": current_balance,
            "cost_per_unit": unit_cost,
            "total_cost": int(purchase.total or (qty * unit_cost)),
            "reference_type": "purchase",
            "reference_id": purchase.id,
            "description": f"شراء من مورد #{purchase.supplier_id if purchase.supplier_id else 'غير محدد'}"
        })
    
    # ==========================
    # 3. المبيعات (Sales)
    # ==========================
    order_items = OrderItem.query.filter_by(product_id=product_id).join(Invoice).order_by(OrderItem.id).all()
    
    for item in order_items:
        invoice = item.invoice
        if not invoice:
            continue
        line_branch_id = item.fulfillment_branch_id or getattr(invoice, "branch_id", None)
        if branch_id and line_branch_id != branch_id:
            continue

        qty = int(item.quantity or 0)
        current_balance -= qty
        movements.append({
            "date": invoice.created_at.date() if invoice.created_at else date.today(),
            "type": "sale",
            "type_ar": "بيع",
            "quantity_in": 0,
            "quantity_out": qty,
            "balance_after": current_balance,
            "cost_per_unit": item.cost,
            "total_cost": int(item.cost or 0) * qty,
            "reference_type": "invoice",
            "reference_id": invoice.id,
            "description": f"بيع - فاتورة #{invoice.id} - {qty} قطعة"
        })

        if is_returned(invoice.status, invoice.payment_status) or is_canceled(invoice.status, invoice.payment_status):
            current_balance += qty
            movements.append({
                "date": invoice.created_at.date() if invoice.created_at else date.today(),
                "type": "return_sale",
                "type_ar": "إرجاع مخزون",
                "quantity_in": qty,
                "quantity_out": 0,
                "balance_after": current_balance,
                "cost_per_unit": item.cost,
                "total_cost": int(item.cost or 0) * qty,
                "reference_type": "invoice",
                "reference_id": invoice.id,
                "description": f"إرجاع/إلغاء - فاتورة #{invoice.id} - {qty} قطعة"
            })

    if branch_id:
        from models.branch import StockTransfer

        transfers = (
            StockTransfer.query.filter(
                db.or_(
                    StockTransfer.from_branch_id == branch_id,
                    StockTransfer.to_branch_id == branch_id,
                ),
                StockTransfer.status.in_(["sent", "received"]),
            )
            .order_by(StockTransfer.created_at)
            .all()
        )
        for transfer in transfers:
            for line in transfer.lines:
                if line.product_id != product_id:
                    continue
                if transfer.from_branch_id == branch_id and transfer.status in ("sent", "received"):
                    current_balance -= line.quantity
                    movements.append({
                        "date": (transfer.sent_at or transfer.created_at).date() if (transfer.sent_at or transfer.created_at) else date.today(),
                        "type": "transfer_out",
                        "type_ar": "نقل صادر",
                        "quantity_in": 0,
                        "quantity_out": line.quantity,
                        "balance_after": current_balance,
                        "cost_per_unit": product.buy_price,
                        "total_cost": line.quantity * product.buy_price,
                        "reference_type": "stock_transfer",
                        "reference_id": transfer.id,
                        "description": f"نقل إلى فرع #{transfer.to_branch_id}",
                    })
                if transfer.to_branch_id == branch_id and transfer.status == "received":
                    current_balance += line.quantity
                    movements.append({
                        "date": (transfer.received_at or transfer.created_at).date() if (transfer.received_at or transfer.created_at) else date.today(),
                        "type": "transfer_in",
                        "type_ar": "نقل وارد",
                        "quantity_in": line.quantity,
                        "quantity_out": 0,
                        "balance_after": current_balance,
                        "cost_per_unit": product.buy_price,
                        "total_cost": line.quantity * product.buy_price,
                        "reference_type": "stock_transfer",
                        "reference_id": transfer.id,
                        "description": f"نقل من فرع #{transfer.from_branch_id}",
                    })
    
    movements.sort(key=lambda x: (x["date"], x["reference_id"]))
    running_balance = 0
    for movement in movements:
        running_balance += int(movement.get("quantity_in") or 0)
        running_balance -= int(movement.get("quantity_out") or 0)
        movement["balance_after"] = running_balance
    
    return movements


def get_product_inventory_summary(product_id):
    """
    حساب ملخص حركات المخزون لمنتج محدد
    
    Returns:
        dict: ملخص الحركات (إجمالي وارد، إجمالي صادر، الرصيد الحالي)
    """
    movements = get_product_inventory_movements(product_id)
    
    total_in = sum(m["quantity_in"] for m in movements)
    total_out = sum(m["quantity_out"] for m in movements)
    current_balance = (movements[-1]["balance_after"] if movements else 0)
    
    # التحقق من تطابق الرصيد
    product = Product.query.get(product_id)
    actual_quantity = int(product.quantity or 0) if product else 0
    try:
        from models.branch import BranchStock

        rows_count = BranchStock.query.filter_by(product_id=product_id).count()
        if rows_count:
            actual_quantity = int(
                db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0))
                .filter(BranchStock.product_id == product_id)
                .scalar()
                or 0
            )
    except Exception:
        db.session.rollback()
    
    return {
        "product_id": product_id,
        "product_name": product.name if product else "",
        "total_in": total_in,
        "total_out": total_out,
        "calculated_balance": current_balance,
        "actual_quantity": actual_quantity,
        "movements_count": len(movements),
        "is_balanced": current_balance == actual_quantity,
        "difference": actual_quantity - current_balance
    }


def get_all_products_movements_summary():
    """
    حساب ملخص حركات المخزون لجميع المنتجات
    
    Returns:
        list: قائمة ملخصات لكل منتج
    """
    products = Product.query.all()
    summaries = []
    
    for product in products:
        summary = get_product_inventory_summary(product.id)
        summaries.append(summary)
    
    return summaries


def validate_sale_quantity(product_id, requested_quantity, branch_id=None):
    """
    التحقق من توفر الكمية قبل البيع
    
    Args:
        product_id: معرف المنتج
        requested_quantity: الكمية المطلوبة للبيع
        branch_id: فرع محدد (اختياري)
        
    Returns:
        dict: {
            "valid": bool,
            "available": int,
            "message": str
        }
    """
    product = Product.query.get(product_id)
    
    if not product:
        return {
            "valid": False,
            "available": 0,
            "message": "المنتج غير موجود"
        }
    
    if not product.active:
        return {
            "valid": False,
            "available": product.quantity,
            "message": "المنتج غير نشط"
        }

    if branch_id:
        from utils.branch_stock_service import get_branch_stock
        available = get_branch_stock(branch_id, product_id)
    else:
        available = product.quantity
    
    if available < requested_quantity:
        return {
            "valid": False,
            "available": available,
            "message": f"الكمية المتوفرة ({available}) أقل من المطلوب ({requested_quantity})"
        }
    
    return {
        "valid": True,
        "available": available,
        "message": "الكمية متوفرة"
    }


def get_low_stock_products(threshold=5):
    """
    جلب المنتجات منخفضة المخزون
    
    Args:
        threshold: الحد الأدنى للمخزون (افتراضي 5)
        
    Returns:
        list: قائمة المنتجات منخفضة المخزون
    """
    products = Product.query.filter(
        Product.quantity <= threshold,
        Product.active == True
    ).all()
    
    return [
        {
            "id": p.id,
            "name": p.name,
            "quantity": p.quantity,
            "buy_price": p.buy_price,
            "threshold": threshold,
            "status": "نافد" if p.quantity == 0 else "منخفض"
        }
        for p in products
    ]


def get_out_of_stock_products():
    """
    جلب المنتجات النافدة من المخزون
    
    Returns:
        list: قائمة المنتجات النافدة
    """
    return get_low_stock_products(threshold=0)
