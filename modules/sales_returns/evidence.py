"""Read original invoice/consumption/payment evidence without posting or DDL."""
import hashlib
import json
from sqlalchemy import inspect
from extensions import db
from models.inventory_lot import OrderItemCostLayer
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.shipping_payment import ShippingPayment
from modules.inventory_locations.lots import placement
from utils.order_stock_policy import is_physical_order_item
from .models import ReturnEvidenceError


def encoded(snapshot):
    value = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value, hashlib.sha256(value.encode("utf-8")).hexdigest()


def _time(value):
    return value.isoformat() if value else None


def capture(invoice):
    """The posting workflow will validate provider/period/scope and save once.

    Missing historical lot or payment information remains explicitly missing.
    This reader never creates fallback stock, changes quantity, seeds a ledger,
    or treats an old paid counter as dated receipt evidence.
    """
    if db.session.is_modified(invoice, include_collections=True):
        raise ReturnEvidenceError("احفظ أو تراجع عن تعديل الفاتورة قبل تثبيت دليل أصل البيع")
    with db.session.no_autoflush:
        return _capture(invoice)


def _capture(invoice):
    inspector = inspect(db.session.connection())
    layers_available = inspector.has_table(OrderItemCostLayer.__tablename__)
    payments_available = inspector.has_table(InvoicePaymentLedger.__tablename__)
    rows = OrderItem.query.filter_by(invoice_id=invoice.id).order_by(OrderItem.id).all()
    lines = []
    for item in rows:
        if db.session.is_modified(item, include_collections=False):
            raise ReturnEvidenceError("تغير بند البيع ولم يحفظ بعد؛ لا يمكن تثبيت دليل متداخل")
        layers = OrderItemCostLayer.query.filter_by(order_item_id=item.id).order_by(
            OrderItemCostLayer.id).all() if layers_available else []
        costs = []
        for layer in layers:
            if db.session.is_modified(layer, include_collections=False):
                raise ReturnEvidenceError("تغير دليل الكلفة ولم يحفظ بعد؛ راجع أصل البيع")
            lot = layer.inventory_lot
            costs.append({"id": layer.id, "lot_id": layer.inventory_lot_id,
                "quantity": layer.quantity, "unit_cost": layer.unit_cost,
                "received_at": _time(lot.created_at) if lot else None,
                "branch_id": lot.branch_id if lot else None,
                "location_id": placement(lot) if lot else None,
                "basis": "saved_fifo" if lot and lot.created_at else "saved_layer_cost"})
        lines.append({"id": item.id, "product_id": item.product_id, "name": item.product_name,
            "quantity": item.quantity, "price": item.price, "value": item.total,
            "discount": item.discount_value, "saved_unit_cost": item.cost,
            "variant": item.variant_color, "sale_mode": item.sale_mode,
            "trade_in_product_id": item.trade_in_source_product_id,
            "trade_in_product_name": item.trade_in_source_product_name,
            "fulfillment_branch_id": item.fulfillment_branch_id, "warehouse_id": item.warehouse_id,
            "physical": is_physical_order_item(item), "cost_layers": costs,
            "cost_basis": "saved_layers" if costs else "saved_line_cost"})
    payments = InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(
        InvoicePaymentLedger.id).all() if payments_available else []
    settlements = ShippingPayment.query.filter_by(invoice_id=invoice.id).order_by(
        ShippingPayment.id).all() if inspector.has_table(ShippingPayment.__tablename__) else []
    from .collections import capture_undated_collection
    return {"basis_version": 1, "invoice": {"id": invoice.id, "branch_id": invoice.branch_id,
        "customer_id": invoice.customer_id, "customer_name": invoice.customer_name,
        "total": invoice.total, "paid_counter": invoice.paid_amount,
        "discount": invoice.discount_amount, "shipping_fee": invoice.shipping_fee,
        "currency": invoice.currency, "exchange_rate": invoice.exchange_rate,
        "status": invoice.status, "payment_status": invoice.payment_status,
        "shipping_company_id": invoice.shipping_company_id,
        "delivery_agent_id": invoice.delivery_agent_id, "shipping_status": invoice.shipping_status,
        "barcode": invoice.barcode, "shipping_barcode": invoice.shipping_barcode,
        "shipping_barcodes_json": invoice.shipping_barcodes_json,
        "stock_is_deducted": invoice.stock_is_deducted, "created_at": _time(invoice.created_at),
        "source_module": invoice.source_module}, "lines": lines,
        "payment_basis": "dated_movements" if payments else "saved_paid_counter",
        "undated_collection": capture_undated_collection(invoice, payments),
        "shipping_settlements": [{"id": row.id, "company_id": row.shipping_company_id,
            "treasury_account_id": row.treasury_account_id, "branch_id": row.branch_id,
            "amount": row.amount, "action": row.action, "recorded_at": _time(row.created_at)}
            for row in settlements],
        "payments": [{"id": row.id, "amount": row.amount_delta,
            "treasury_account_id": row.treasury_account_id, "method": row.payment_method,
            "source_module": row.source_module, "recorded_at": _time(row.recorded_at)} for row in payments]}
