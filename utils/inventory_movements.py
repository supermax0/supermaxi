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
from models.order_item import OrderItem
from models.invoice import Invoice
from extensions import db


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
    current_balance = product.opening_stock or 0
    
    # ==========================
    # 1. المخزون الافتتاحي
    # ==========================
    if product.opening_stock and product.opening_stock > 0:
        movements.append({
            "date": product.created_at.date() if product.created_at else date.today(),
            "type": "opening_stock",
            "type_ar": "مخزون افتتاحي",
            "quantity_in": product.opening_stock,
            "quantity_out": 0,
            "balance_after": current_balance,
            "cost_per_unit": product.buy_price,
            "total_cost": product.opening_stock * product.buy_price,
            "reference_type": "product",
            "reference_id": product.id,
            "description": f"مخزون افتتاحي - {product.name}"
        })
    
    # ==========================
    # 2. المشتريات (Purchases)
    # ==========================
    purchases = Purchase.query.filter_by(product_id=product_id).order_by(Purchase.created_at).all()
    for purchase in purchases:
        current_balance += purchase.quantity
        movements.append({
            "date": purchase.purchase_date if purchase.purchase_date else (purchase.created_at.date() if purchase.created_at else date.today()),
            "type": "purchase",
            "type_ar": "شراء",
            "quantity_in": purchase.quantity,
            "quantity_out": 0,
            "balance_after": current_balance,
            "cost_per_unit": purchase.price,
            "total_cost": purchase.total,
            "reference_type": "purchase",
            "reference_id": purchase.id,
            "description": f"شراء من مورد #{purchase.supplier_id if purchase.supplier_id else 'غير محدد'}"
        })
    
    # ==========================
    # 3. المبيعات (Sales)
    # ==========================
    # جلب جميع OrderItems للمنتج
    order_items = OrderItem.query.filter_by(product_id=product_id).join(Invoice).filter(
        Invoice.status != "مرتجع",
        Invoice.payment_status != "مرتجع"
    ).order_by(OrderItem.id).all()
    
    for item in order_items:
        # التحقق من حالة الفاتورة (لا نحسب المرتجعات هنا)
        invoice = item.invoice
        if invoice and invoice.status != "مرتجع" and getattr(invoice, "payment_status", None) != "مرتجع":
            current_balance -= item.quantity
            movements.append({
                "date": invoice.created_at.date() if invoice.created_at else date.today(),
                "type": "sale",
                "type_ar": "بيع",
                "quantity_in": 0,
                "quantity_out": item.quantity,
                "balance_after": current_balance,
                "cost_per_unit": item.cost,  # تكلفة الوحدة وقت البيع
                "total_cost": item.cost * item.quantity,  # COGS
                "reference_type": "invoice",
                "reference_id": invoice.id,
                "description": f"بيع - فاتورة #{invoice.id} - {item.quantity} قطعة"
            })
    
    # ==========================
    # 4. المرتجعات (Returns)
    # ==========================
    # المرتجعات تُعيد الكمية للمخزون
    returned_invoices = Invoice.query.filter(
        db.or_(
            Invoice.payment_status == "مرتجع",
            Invoice.status == "مرتجع"
        )
    ).join(OrderItem).filter(
        OrderItem.product_id == product_id
    ).all()
    
    for invoice in returned_invoices:
        # جلب OrderItems المرتجعة
        returned_items = OrderItem.query.filter_by(
            invoice_id=invoice.id,
            product_id=product_id
        ).all()
        
        for item in returned_items:
            current_balance += item.quantity  # إعادة الكمية للمخزون
            movements.append({
                "date": invoice.created_at.date() if invoice.created_at else date.today(),
                "type": "return_sale",
                "type_ar": "مرتجع بيع",
                "quantity_in": item.quantity,
                "quantity_out": 0,
                "balance_after": current_balance,
                "cost_per_unit": item.cost,  # نفس التكلفة وقت البيع
                "total_cost": item.cost * item.quantity,
                "reference_type": "invoice",
                "reference_id": invoice.id,
                "description": f"مرتجع بيع - فاتورة #{invoice.id} - {item.quantity} قطعة"
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
    
    # ترتيب الحركات حسب التاريخ
    movements.sort(key=lambda x: (x["date"], x["reference_id"]))
    
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
    actual_quantity = product.quantity if product else 0
    
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
