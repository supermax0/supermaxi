"""Options across real tenant catalog, purchasing, cart, invoice and stock."""
import json
from pathlib import Path

import pytest
from tests.test_desktop_product_colors import inventory  # noqa: F401


def size_payload(stock=6):
    return {"axes": ["الحجم"], "expected_stock": stock, "rows": [
        {"name": "الحجم: 50 مل", "attributes": {"الحجم": "50 مل"}, "qty": 2,
         "sale_price": 180, "buy_price": 110, "active": True},
        {"name": "الحجم: 100 مل", "attributes": {"الحجم": "100 مل"}, "qty": 4,
         "sale_price": 250, "buy_price": 140, "active": True},
    ]}


def save_options(inventory, monkeypatch, payload=None):
    product, stock, update, routes = inventory
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    payload = payload or size_payload()
    body, status = update({"product_options": json.dumps(payload, ensure_ascii=False)})
    assert status == 200, body
    return product, stock, update, routes


def edit_payload(product):
    from utils.desktop_product_colors import local_color_rows
    from utils.product_options import option_config
    return {"axes": option_config(product)["axes"], "expected_stock": product.quantity,
            "rows": local_color_rows(product.id)}


def test_size_only_conversion_preserves_stock_metadata_and_identity(inventory, monkeypatch):
    from utils.desktop_product_colors import local_color_rows
    from utils.product_color_service import colors_for_product_dict
    product, stock, _, _ = save_options(inventory, monkeypatch)
    assert product.quantity == stock.quantity == 6
    assert product.opening_stock == stock.opening_stock == 10
    assert json.loads(product.meta_json)["specs"] == {"capacity": "13"}
    rows = local_color_rows(product.id)
    assert {r["name"]: r["qty"] for r in rows} == {"الحجم: 50 مل": 2, "الحجم: 100 مل": 4}
    assert len({r["id"] for r in rows}) == 2
    assert colors_for_product_dict(product)["option_axes"] == ["الحجم"]


@pytest.mark.parametrize("mutation", ["stock", "duplicate", "unknown_id", "fraction", "delimiter", "empty_axes"])
def test_invalid_options_are_atomic(inventory, monkeypatch, mutation):
    product, stock, update, routes = inventory
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    payload = size_payload()
    if mutation == "stock": payload["expected_stock"] = 7
    if mutation == "duplicate": payload["rows"][1] = dict(payload["rows"][0])
    if mutation == "unknown_id": payload["rows"][0]["id"] = 12345
    if mutation == "fraction": payload["rows"][0]["qty"] = 1.5
    if mutation == "delimiter": payload["rows"][0]["attributes"]["الحجم"] = "a|b"
    if mutation == "empty_axes": payload["axes"] = []
    body, status = update({"name": "Must rollback", "product_options": json.dumps(payload)})
    assert status == 409, body
    assert product.name == "Washer" and product.quantity == stock.quantity == 6
    from models.product_color_variant import ProductColorVariant
    assert ProductColorVariant.query.filter_by(product_id=product.id).count() == 0


def test_option_price_permissions_and_inheritance(inventory, monkeypatch):
    from utils.product_color_service import effective_color_sale_price
    product, _, update, routes = save_options(inventory, monkeypatch)
    monkeypatch.setattr(routes, "check_permission", lambda key: key == "can_manage_inventory")
    payload = edit_payload(product)
    payload["rows"][0]["sale_price"] = 999
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 409 and "صلاحية" in body["error"]
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    payload["rows"][0]["sale_price"] = None
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 200, body
    assert effective_color_sale_price(product, payload["rows"][0]["name"]) == product.sale_price


def test_size_color_distribution_and_archiving_keep_old_history(inventory, monkeypatch):
    from extensions import db
    from models.product_color_variant import ProductColorVariant
    from utils.product_options import validate_selection
    from utils.product_color_service import ProductColorError, receive_color_stock
    product, stock, update, _ = save_options(inventory, monkeypatch)
    payload = edit_payload(product)
    source = next(r for r in payload["rows"] if r["name"] == "الحجم: 100 مل")
    payload["axes"].append("اللون")
    for row in payload["rows"]:
        row["attributes"]["اللون"] = "غير محدد"
        row["active"] = False
    payload["rows"].append({"name": "الحجم: 100 مل / اللون: أسود", "attributes": {"الحجم": "100 مل", "اللون": "أسود"},
                            "qty": 4, "source_id": source["id"], "active": True})
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 200, body
    old = db.session.get(ProductColorVariant, source["id"])
    assert old.quantity == 0 and old.color_name == source["name"]
    assert product.quantity == stock.quantity == 6
    with pytest.raises(ProductColorError): validate_selection(product, old.color_name)
    # Old returns still credit the original variant, even after it is archived.
    receive_color_stock(product.id, old.color_name, 1, branch_id=product.branch_id)
    db.session.commit()
    assert old.quantity == 1 and product.quantity == stock.quantity == 7


def test_identity_and_existing_stock_cannot_be_overwritten_by_catalog_edits(inventory, monkeypatch):
    product, stock, update, _ = save_options(inventory, monkeypatch)
    payload = edit_payload(product)
    payload["rows"][0]["qty"] = 10000
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 200, body
    assert product.quantity == stock.quantity == 6
    payload["rows"][0]["attributes"]["الحجم"] = "200 مل"
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 409, body


@pytest.mark.parametrize("lifecycle", ["cancel", "return"])
def test_full_purchase_store_invoice_cancel_path(inventory, monkeypatch, lifecycle):
    from flask import current_app
    from extensions import db
    from models.supplier import Supplier
    from models.invoice import Invoice
    from models.product_color_variant import ProductColorVariant
    from routes.purchases import _create_purchase_from_payload, _ensure_purchase_schema, _reverse_purchase_item_stock
    from modules.storefront.services.cart_service import StorefrontCartService
    import modules.storefront.services.cart_service as cart_module
    from modules.storefront.services.checkout_service import StorefrontCheckoutService
    import modules.storefront.services.checkout_service as checkout_module
    from utils.order_lifecycle import process_order_cancel, process_order_return
    product, stock, _, _ = save_options(inventory, monkeypatch)
    selected = ProductColorVariant.query.filter_by(product_id=product.id, color_name="الحجم: 100 مل").one()
    supplier = Supplier(name="Option Supplier", branch_id=product.branch_id)
    db.session.add(supplier); db.session.commit()
    monkeypatch.setattr(cart_module, "cash_store_product_is_visible", lambda _: True)
    monkeypatch.setattr(cart_module, "published_installment_item", lambda _: None)
    monkeypatch.setattr(checkout_module, "deferred_stock_enabled", lambda: False)
    monkeypatch.setattr(checkout_module, "get_default_branch", lambda: db.session.get(__import__('models.branch', fromlist=['Branch']).Branch, product.branch_id))
    with current_app.test_request_context("/shop/test/product/1"):
        _ensure_purchase_schema()
        purchase, error = _create_purchase_from_payload({"supplier_id": supplier.id, "_validated_branch_id": product.branch_id,
            "status": "confirmed", "purchase_mode": "credit", "items": [{"product_id": product.id,
            "variant_id": selected.id, "quantity": 3, "unit_cost": 140}]}, {})
        assert purchase is not None, error
        assert selected.quantity == 7 and product.quantity == stock.quantity == 9
        assert purchase.items[0].variant_color == selected.color_name
        printed = current_app.jinja_env.get_template("purchase_print.html").render(purchase=purchase,
            effective_paid_total=0, effective_remaining_total=purchase.grand_total, effective_supplier_balance=0)
        assert selected.color_name in printed
        cart = StorefrontCartService("test")
        ok, message = cart.try_add(product.id, 2, color=selected.color_name)
        assert ok, message
        items = cart.items()
        assert items[0]["price"] == 250 and items[0]["line_total"] == 500
        from modules.storefront.services.settings_service import StorefrontSettingsService
        checkout_html = current_app.jinja_env.get_template("storefront/checkout.html").render(
            cart_items=items, store_design=StorefrontSettingsService().design_settings(),
            shop_tenant_slug="test", store_account=None, checkout_form={}, shipping_map={},
            shipping_fee=0, shipping_default_fee=0, net_subtotal=500, subtotal=500,
            discount_amount=0, grand_total=500)
        assert selected.color_name in checkout_html
        checkout = StorefrontCheckoutService()
        ok, message, data = checkout.create_invoice_from_cart(items, {"customer_name": "Options Customer", "phone": "07712345678",
            "city": "بغداد", "address": "شارع اختبار الخيارات"}, 0, 0)
        assert ok, message
        invoice = db.session.get(Invoice, data["invoice_id"])
        line = next(item for item in invoice.items if item.product_id == product.id)
        assert line.variant_color == selected.color_name and line.price == 250 and line.cost == 140
        assert selected.color_name in line.display_name
        from utils.order_shipping import prepare_invoice_items_for_print
        from models.invoice_settings import InvoiceSettings
        printable, total = prepare_invoice_items_for_print(invoice.items)
        invoice_html = current_app.jinja_env.get_template("invoice.html").render(order=invoice, items=printable,
            settings=InvoiceSettings.get_settings(), total=total, total_before_discount=total, discount_amount=0,
            due=total, paid_amount=0, is_partial=False, returned_count=0, cancelled_count=0)
        assert selected.color_name in invoice_html
        assert selected.quantity == 5 and product.quantity == stock.quantity == 7
        if lifecycle == "return":
            invoice.status = "جاري الشحن"
            process_order_return(invoice, str(invoice.id))
        else:
            process_order_cancel(invoice)
        db.session.commit()
        assert selected.quantity == 7 and product.quantity == stock.quantity == 9
        if lifecycle == "return": process_order_return(invoice, str(invoice.id))
        else: process_order_cancel(invoice)
        db.session.commit()
        assert selected.quantity == 7
        assert _reverse_purchase_item_stock(purchase, purchase.items[0], product.branch_id)
        db.session.commit()
        assert selected.quantity == 4 and product.quantity == stock.quantity == 6
        assert not _reverse_purchase_item_stock(purchase, purchase.items[0], product.branch_id)


def test_cart_quantity_updates_keep_option_stock_and_reject_archived_choices(inventory, monkeypatch):
    from flask import current_app
    from modules.storefront.services.cart_service import StorefrontCartService
    import modules.storefront.services.cart_service as cart_module
    product, _, update, _ = save_options(inventory, monkeypatch)
    monkeypatch.setattr(cart_module, "cash_store_product_is_visible", lambda _: True)
    monkeypatch.setattr(cart_module, "published_installment_item", lambda _: None)
    with current_app.test_request_context("/shop/test/cart"):
        cart = StorefrontCartService("test")
        large, small = "الحجم: 100 مل", "الحجم: 50 مل"
        assert cart.try_add(product.id, 2, color=large)[0]
        assert cart.try_add(product.id, 1, color=small)[0]
        before = cart.cart_raw()
        large_key = cart._line_key(product.id, large)
        small_key = cart._line_key(product.id, small)
        assert not cart.try_update_quantities({large_key: 5})[0]
        assert cart.cart_raw() == before
        assert cart.try_update_quantities({large_key: 4, small_key: 2})[0]
        # Separate sale-mode lines still share one physical option balance.
        cart.add(product.id, 1, color=large, sale_mode="installment")
        before = cart.cart_raw()
        assert not cart.try_update_quantities({large_key: 4})[0]
        assert cart.cart_raw() == before
        assert cart.try_update_quantities({large_key: 3})[0]
        payload = edit_payload(product)
        for row in payload["rows"]:
            if row["name"] == large:
                row["active"] = False
        body, status = update({"product_options": json.dumps(payload)})
        assert status == 200, body
        assert not cart.try_add(product.id, 1, color=large)[0]
        assert not cart.try_update_quantities({large_key: 1})[0]
        assert cart.try_update_quantities({large_key: 0, cart._line_key(product.id, large, "installment"): 0})[0]
        assert list(cart.cart_raw()) == [small_key]


def test_size_store_template_emits_axes_prices_and_available_stock(inventory, monkeypatch):
    from flask import current_app
    from modules.storefront.services.product_presenter import product_card
    from modules.storefront.services.settings_service import StorefrontSettingsService
    product, _, _, _ = save_options(inventory, monkeypatch)
    with current_app.test_request_context("/shop/test/product/1"):
        card = product_card(product, "test")
        html = current_app.jinja_env.get_template("storefront/_color_picker.html").render(product=card)
        assert 'data-sf-option-axis="الحجم"' in html and 'data-price="250"' in html
        design = StorefrontSettingsService().design_settings()
        design.update(store_name="FINORA", primary_color="#7645ed", ai_assistant_enabled=False)
        import base64
        def picture(fill):
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" rx="24" fill="{fill}"/><text x="200" y="215" text-anchor="middle" fill="white" font-size="48">FINORA</text></svg>'
            return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        for index, row in enumerate(card["colors"]):
            row["image_url"] = picture("#8758db" if index == 0 else "#289784")
        card["name"] = "عطر FINORA — خيارات الحجم"
        html = current_app.jinja_env.get_template("storefront/product_detail.html").render(
            product=card, related_products=[], store_design=design, shop_tenant_slug="test", cart_count=0,
            store_account=None, favorite_ids=[], favorite_count=0, store_sale_products=[card], help_fields_json="{}", current_year=2026)
        (Path(__file__).parent / "_artifacts" / "product-options-store-preview.html").write_text(html, encoding="utf-8")
        card.update(name="قميص FINORA — اللون والمقاس", option_axes=["المقاس", "اللون"], colors=[
            {"name": "المقاس: M / اللون: أسود", "attributes": {"المقاس": "M", "اللون": "أسود"}, "qty": 2, "available_qty": 2, "sale_price": 180, "image_url": picture("#292633"), "active": True},
            {"name": "المقاس: M / اللون: أبيض", "attributes": {"المقاس": "M", "اللون": "أبيض"}, "qty": 0, "available_qty": 0, "sale_price": 200, "image_url": picture("#aca9b5"), "active": True},
            {"name": "المقاس: L / اللون: أسود", "attributes": {"المقاس": "L", "اللون": "أسود"}, "qty": 4, "available_qty": 4, "sale_price": 250, "image_url": picture("#292633"), "active": True},
        ])
        html = current_app.jinja_env.get_template("storefront/product_detail.html").render(
            product=card, related_products=[], store_design=design, shop_tenant_slug="test", cart_count=0,
            store_account=None, favorite_ids=[], favorite_count=0, store_sale_products=[card], help_fields_json="{}", current_year=2026)
        (Path(__file__).parent / "_artifacts" / "product-options-combination-preview.html").write_text(html, encoding="utf-8")


def test_web_edit_preserves_options_and_uses_same_atomic_image_save(inventory, monkeypatch, tmp_path):
    from flask import current_app
    from io import BytesIO
    from PIL import Image
    from utils.product_options import option_config
    from utils.desktop_product_colors import local_color_rows
    import utils.product_color_media as media
    product, stock, _, routes = save_options(inventory, monkeypatch)
    monkeypatch.setattr(routes, "_branch_id_for_product_stock", lambda *args, **kwargs: product.branch_id)
    monkeypatch.setattr(media, "_upload_folder", lambda: tmp_path / "photos")
    image = BytesIO(); Image.new("RGB", (12, 10), "red").save(image, "PNG"); image.seek(0)
    with current_app.test_request_context("/inventory/add", method="POST", data={
            "edit_product_id": product.id, "name": product.name, "buy_price": "100", "sale_price": "150",
            "current_stock": "999", "color_images": json.dumps([{"name": "الحجم: 100 مل", "field": "color_image_0"}]),
            "color_image_0": (image, "photo.png")}):
        response = routes.add_product_page()
        assert response.status_code == 302
    assert product.quantity == stock.quantity == 6
    assert option_config(product)["axes"] == ["الحجم"]
    assert any(row["image_url"] for row in local_color_rows(product.id))
    with current_app.test_request_context("/inventory/options-preview"):
        # Render the real editor for a browser check, without account data.
        html = current_app.jinja_env.get_template("inventory/_product_options_editor.html").render(
            edit_product=None, edit_current_stock=0, product_option_rows=[], m={})
        (Path(__file__).parent / "_artifacts" / "product-options-web-editor-preview.html").write_text(
            '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><body><form action="/inventory/save" method="post" enctype="multipart/form-data">'
            '<label>اسم المنتج<input name="name" value="عطر" required></label><input name="opening_stock" type="number" value="6">'
            + html + '<button type="submit">حفظ المنتج</button></form></body></html>', encoding="utf-8")


def test_option_conversion_and_distribution_respect_device_holds(inventory, monkeypatch):
    from extensions import db
    from uuid import uuid4
    from utils.desktop_stock_reservations import ensure_reservation_schema, DesktopStockAllocation
    product, stock, update, routes = inventory
    monkeypatch.setattr(routes, "check_permission", lambda key: True)
    ensure_reservation_schema()
    allocation = DesktopStockAllocation(id=str(uuid4()), grant_id="option-hold", requested_product_id=product.id,
        product_id=product.id, stock_id=stock.id, variant_id=0, branch_id=product.branch_id, color="", quantity=1, consumed=0, returned=0)
    db.session.add(allocation); db.session.commit()
    body, status = update({"product_options": json.dumps(size_payload())})
    assert status == 409 and "أوفلاين" in body["error"]
    assert product.quantity == stock.quantity == 6
    allocation.returned = allocation.quantity
    db.session.commit()
    save_options(inventory, monkeypatch)
    payload = edit_payload(product)
    source = payload["rows"][0]
    db.session.add(DesktopStockAllocation(id=str(uuid4()), grant_id="option-hold-2", requested_product_id=product.id,
        product_id=product.id, stock_id=stock.id, variant_id=source["id"], branch_id=product.branch_id,
        color=source["name"], quantity=source["qty"], consumed=0, returned=0))
    db.session.commit()
    payload["rows"].append({"attributes": {"الحجم": "200 مل"}, "qty": source["qty"], "source_id": source["id"]})
    body, status = update({"product_options": json.dumps(payload)})
    assert status == 409 and "المتاح" in body["error"]
    assert product.quantity == stock.quantity == 6


def test_public_store_api_exposes_option_photos_prices_and_stock_without_costs(inventory, monkeypatch):
    from flask import current_app
    from modules.storefront.services.product_presenter import product_card
    from modules.store_api.services.catalog import public_product
    product, _, _, _ = save_options(inventory, monkeypatch)
    with current_app.test_request_context("/api/v1/store/products"):
        result = public_product(product_card(product, "test"), currency="د.ع")
        assert result["has_options"] and result["option_axes"] == ["الحجم"]
        assert {row["price"] for row in result["variants"]} == {180, 250}
        assert all("buy_price" not in row for row in result["variants"])


def test_purchase_option_invoice_edit_changes_only_variant_delta(inventory, monkeypatch):
    from flask import current_app, session
    from extensions import db
    from models.employee import Employee
    from models.supplier import Supplier
    from models.product_color_variant import ProductColorVariant
    from routes.purchases import _create_purchase_from_payload, _ensure_purchase_schema, unlock_purchase_for_edit, update_purchase
    product, stock, _, _ = save_options(inventory, monkeypatch)
    employee = Employee(name="Options Admin", username="options_admin", password="test", role="admin", is_active=True, branch_id=product.branch_id)
    supplier = Supplier(name="Option edit Supplier", branch_id=product.branch_id)
    db.session.add_all([employee, supplier]); db.session.commit()
    payload = {"supplier_id": supplier.id, "branch_id": product.branch_id, "status": "confirmed", "purchase_mode": "credit",
        "items": [{"product_id": product.id, "color": "الحجم: 100 مل", "quantity": 2, "unit_cost": 140}]}
    def result(response):
        return (response[0] if isinstance(response, tuple) else response).get_json()
    with current_app.test_request_context("/purchases/create", method="POST"):
        session["user_id"] = employee.id; session["role"] = "admin"
        _ensure_purchase_schema()
        purchase, error = _create_purchase_from_payload({**payload, "_validated_branch_id": product.branch_id}, {})
        assert purchase is not None, error
    selected = ProductColorVariant.query.filter_by(product_id=product.id, color_name="الحجم: 100 مل").one()
    assert selected.quantity == 6 and product.quantity == stock.quantity == 8
    with current_app.test_request_context(f"/purchases/api/{purchase.id}/unlock-edit", method="POST"):
        session["user_id"] = employee.id; session["role"] = "admin"
        data = result(unlock_purchase_for_edit(purchase.id)); assert data["success"], data
    with current_app.test_request_context(f"/purchases/api/{purchase.id}/update", method="POST", json={**payload,
        "items": [{**payload["items"][0], "quantity": 3}]}):
        session["user_id"] = employee.id; session["role"] = "admin"
        data = result(update_purchase(purchase.id)); assert data["success"], data
    db.session.refresh(selected); db.session.refresh(product); db.session.refresh(stock)
    assert selected.quantity == 7 and product.quantity == stock.quantity == 9
