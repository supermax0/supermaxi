from __future__ import annotations

import json
import re
from datetime import datetime

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.branch_migration import get_default_branch
from utils.branch_stock_service import deduct_stock, BranchStockError
from utils.branch_sales import resolve_sale_fulfillment
from utils.order_shipping import add_shipping_line_item, net_total_after_shipping

SERVICE_SHIPPING_BARCODE = "__SF_SHIPPING__"
SERVICE_DISCOUNT_BARCODE = "__SF_DISCOUNT__"


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_or_create_service_product(name: str, barcode: str, tenant_id: int | None) -> Product:
    product = Product.query.filter_by(barcode=barcode, tenant_id=tenant_id).first()
    if product:
        return product
    product = Product(
        name=name,
        barcode=barcode,
        buy_price=0,
        sale_price=0,
        quantity=0,
        active=False,
        tenant_id=tenant_id,
        description="منتج نظامي للمتجر الإلكتروني — لا يظهر في الكatalog",
        meta_json=json.dumps({"storefront_service": True}),
    )
    db.session.add(product)
    db.session.flush()
    return product


class StorefrontCheckoutService:
    def validate_form(self, form_data: dict, cart_items: list[dict]) -> tuple[bool, str]:
        name = str(form_data.get("customer_name") or "").strip()
        phone = str(form_data.get("phone") or "").strip()
        city = str(form_data.get("city") or "").strip()
        address = str(form_data.get("address") or "").strip()

        if not name:
            return False, "يرجى إدخال الاسم الكامل."
        if not phone:
            return False, "يرجى إدخال رقم الهاتف."
        if len(re.sub(r"\D+", "", phone)) < 8:
            return False, "رقم الهاتف غير صحيح."
        if len(city) < 2:
            return False, "يرجى إدخال المحافظة بشكل صحيح."
        if not address:
            return False, "يرجى إدخال العنوان."
        if len(address) < 5:
            return False, "العنوان قصير جداً."
        if not cart_items:
            return False, "سلة الطلب فارغة."

        default_branch = get_default_branch()
        preferred = default_branch.id if default_branch else None
        for item in cart_items:
            _branch_id, check = resolve_sale_fulfillment(
                item["id"],
                item["quantity"],
                preferred_branch_id=preferred,
            )
            if not check.get("valid") or not _branch_id:
                return False, f"المنتج {item['name']}: {str(check.get('message') or 'الكمية غير متوفرة.')}"
        return True, ""

    def create_invoice_from_cart(
        self,
        cart_items: list[dict],
        form_data: dict,
        shipping_fee: int,
        discount_amount: int,
    ) -> tuple[bool, str, dict]:
        ok, msg = self.validate_form(form_data, cart_items)
        if not ok:
            return False, msg, {}

        name = str(form_data.get("customer_name") or "").strip()
        phone = str(form_data.get("phone") or "").strip()
        city = str(form_data.get("city") or "").strip()
        address = str(form_data.get("address") or "").strip()
        notes = str(form_data.get("notes") or "").strip()

        first_product = Product.query.get(cart_items[0]["id"]) if cart_items else None
        tenant_id = getattr(first_product, "tenant_id", None)

        customer = Customer.query.filter_by(phone=phone).first()
        if customer:
            customer.name = name
            if city:
                customer.city = city
            if address:
                customer.address = address
            if notes:
                customer.notes = notes
        else:
            customer = Customer(
                name=name,
                phone=phone,
                city=city or None,
                address=address,
                notes=notes or None,
                tenant_id=tenant_id,
            )
            db.session.add(customer)
            db.session.flush()

        subtotal = sum(int(i["line_total"]) for i in cart_items)
        net_subtotal = max(0, subtotal - discount_amount)
        shipping_fee = max(0, _safe_int(shipping_fee, 0))
        # Delivery is deducted from the customer-facing sale total and kept as an internal line for settlement.
        grand_total = net_total_after_shipping(net_subtotal, shipping_fee)

        default_branch = get_default_branch()
        preferred_branch_id = default_branch.id if default_branch else None

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=None,
            employee_name=None,
            tenant_id=tenant_id,
            branch_id=preferred_branch_id,
            total=grand_total,
            status="تم الطلب",
            payment_status="غير مسدد",
            note=(
                f"طلب من متجر المنتجات | COD | city={city} | "
                f"shipping={shipping_fee} | discount={discount_amount} | notes={notes}"
            ),
            created_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        db.session.flush()

        invoice_branch_id = preferred_branch_id
        for item in cart_items:
            product = Product.query.get(item["id"])
            if not product:
                db.session.rollback()
                return False, f"المنتج غير موجود: {item['name']}", {}
            fulfillment_branch_id, check = resolve_sale_fulfillment(
                product.id,
                item["quantity"],
                preferred_branch_id=preferred_branch_id,
            )
            if not check.get("valid") or not fulfillment_branch_id:
                db.session.rollback()
                return False, f"المنتج {product.name}: {str(check.get('message') or 'الكمية غير متوفرة.')}", {}
            if invoice_branch_id is None:
                invoice_branch_id = fulfillment_branch_id
            line_total = int(product.sale_price or 0) * int(item["quantity"])
            db.session.add(
                OrderItem(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=int(item["quantity"]),
                    price=int(product.sale_price or 0),
                    cost=int(product.buy_price or 0),
                    total=line_total,
                    fulfillment_branch_id=fulfillment_branch_id,
                )
            )
            try:
                deduct_stock(fulfillment_branch_id, product.id, int(item["quantity"]))
            except BranchStockError as exc:
                db.session.rollback()
                return False, str(exc), {}
        if invoice_branch_id:
            invoice.branch_id = invoice_branch_id

        if discount_amount > 0:
            discount_product = _get_or_create_service_product("خصم كوبون", SERVICE_DISCOUNT_BARCODE, tenant_id)
            db.session.add(
                OrderItem(
                    invoice_id=invoice.id,
                    product_id=discount_product.id,
                    product_name="خصم كوبون",
                    quantity=1,
                    price=-discount_amount,
                    cost=0,
                    total=-discount_amount,
                )
            )

        if shipping_fee > 0:
            add_shipping_line_item(invoice, shipping_fee, tenant_id)
            invoice.total = grand_total

        db.session.commit()

        return True, "تم استلام طلبك بنجاح.", {
            "invoice_id": invoice.id,
            "items_count": len(cart_items),
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "net_subtotal": net_subtotal,
            "shipping_fee": shipping_fee,
            "grand_total": grand_total,
            "customer_name": customer.name,
        }
