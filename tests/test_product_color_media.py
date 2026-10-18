"""Per-color photos are atomic, shared correctly, and never adjust stock."""
import json
from io import BytesIO
from pathlib import Path

import pytest
from tests.test_desktop_product_colors import inventory  # noqa: F401


def png(color="white"):
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (12, 10), color).save(output, "PNG")
    output.seek(0)
    return output


@pytest.fixture
def media(inventory, monkeypatch, tmp_path):
    import utils.product_color_media as media_module
    product, stock, update, routes = inventory
    monkeypatch.setattr(media_module, "_upload_folder", lambda: tmp_path / "static" / "uploads" / "products")
    body, status = update({"add_colors": '["أبيض","أسود"]', "color_stock": "6"})
    assert status == 200, body
    return product, stock, update, routes, tmp_path


def photos(update, actions, **files):
    return update({"color_images": json.dumps(actions, ensure_ascii=False), **files})


def test_upload_replace_remove_preserves_stock_and_sanitizes_photos(media):
    from PIL import Image
    from models.product_color_variant import ProductColorVariant
    from utils.product_color_service import get_product_colors
    product, stock, update, _, folder = media
    before = [(row.id, row.quantity, row.buy_price, row.sale_price) for row in ProductColorVariant.query.all()]
    body, status = photos(update, [{"name": "أبيض", "field": "color_image_0"}, {"name": "أسود", "field": "color_image_1"}], color_image_0=(png(), "same.png"), color_image_1=(png("black"), "same.png"))
    assert status == 200, body
    colors = {row["name"]: row for row in get_product_colors(product.id)}
    white = colors["أبيض"]["image_url"]
    assert white != colors["أسود"]["image_url"]
    with Image.open(folder / white.lstrip("/")) as image:
        assert image.format == "WEBP" and image.size == (12, 10)
    body, status = photos(update, [{"name": "أبيض", "field": "color_image_0"}], color_image_0=(png("red"), "replace.png"))
    assert status == 200, body
    assert get_product_colors(product.id)[0]["image_url"] != white
    body, status = photos(update, [{"name": "أبيض", "remove": True}])
    assert status == 200, body
    assert {row["name"]: row["image_url"] for row in get_product_colors(product.id)}["أبيض"] == ""
    assert [(row.id, row.quantity, row.buy_price, row.sale_price) for row in ProductColorVariant.query.all()] == before
    assert product.quantity == stock.quantity == 6


@pytest.mark.parametrize("actions,invalid", [
    ([{"name": [], "remove": True}], False),
    ([{"name": "Unknown", "remove": True}], False),
    ([{"name": "أبيض", "remove": True}, {"name": "أبيض", "remove": True}], False),
    ([{"name": "أبيض", "field": "color_image_0"}, {"name": "أسود", "field": "color_image_1"}], True),
])
def test_invalid_batch_rolls_back_product_edit_and_creates_no_files(media, actions, invalid):
    product, stock, update, _, folder = media
    data = {"name": "Should rollback", "color_images": json.dumps(actions)}
    if invalid:
        data.update(color_image_0=(png(), "valid.png"), color_image_1=(BytesIO(b"not an image"), "invalid.png"))
    body, status = update(data)
    assert status == 409, body
    assert product.name == "Washer" and product.quantity == stock.quantity == 6
    assert not list(folder.rglob("color_*.webp"))


def test_shared_branch_photo_is_visible_without_changing_other_branch_stock(media):
    from extensions import db
    from flask import g
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.product_color_service import get_product_colors
    product, stock, update, _, _ = media
    g.independent_branches_enabled = False
    g.view_all_branches = True
    branch = Branch(code="PHOTO2", name="Photo2", is_active=True)
    db.session.add(branch)
    db.session.flush()
    copy = Product(branch_id=branch.id, catalog_group_id=product.catalog_group_id, name=product.name, quantity=4, buy_price=88, sale_price=199, active=True, meta_json='{"has_colors":true}')
    db.session.add(copy)
    db.session.flush()
    other = BranchStock(branch_id=branch.id, product_id=copy.id, quantity=4)
    db.session.add_all([other, ProductColorVariant(product_id=copy.id, color_name="أبيض", quantity=4, buy_price=88, sale_price=199)])
    db.session.commit()
    body, status = photos(update, [{"name": "أبيض", "field": "color_image_0"}], color_image_0=(png(), "white.png"))
    assert status == 200, body
    assert get_product_colors(copy.id)[0]["image_url"] == get_product_colors(product.id)[0]["image_url"]
    assert (stock.quantity, other.quantity, copy.sale_price) == (6, 4, 199)
    g.independent_branches_enabled = True
    assert get_product_colors(copy.id)[0]["image_url"] == ""


def test_photo_edit_is_allowed_while_existing_color_stock_is_reserved_offline(media):
    from extensions import db
    from models.product_color_variant import ProductColorVariant
    from utils.desktop_stock_reservations import ensure_reservation_schema, DesktopStockAllocation
    from utils.product_color_service import get_product_colors
    from uuid import uuid4
    product, stock, update, _, _ = media
    variant = ProductColorVariant.query.filter_by(product_id=product.id, color_name="أبيض").one()
    ensure_reservation_schema()
    db.session.add(DesktopStockAllocation(id=str(uuid4()), grant_id="photo-hold", requested_product_id=product.id,
        product_id=product.id, stock_id=stock.id, variant_id=variant.id, branch_id=product.branch_id,
        color="أبيض", quantity=2, consumed=0, returned=0))
    db.session.commit()
    body, status = photos(update, [{"name": "أبيض", "field": "color_image_0"}], color_image_0=(png(), "white.png"))
    assert status == 200, body
    assert get_product_colors(product.id)[0]["image_url"]
    assert product.quantity == stock.quantity == variant.quantity == 6
    assert DesktopStockAllocation.query.one().quantity == 2


def test_creating_colored_product_with_photos_is_one_atomic_save(media, monkeypatch):
    from flask import current_app
    from models.product import Product
    from utils.product_color_service import get_product_colors
    product, _, _, routes, folder = media
    monkeypatch.setattr(routes, "resolve_write_branch_id", lambda _: product.branch_id)
    monkeypatch.setattr(routes, "_branch_id_for_product_stock", lambda *args, **kwargs: product.branch_id)
    def create(data):
        with current_app.test_request_context("/inventory/add", method="POST", data=data):
            result = routes.add_product_page()
            response, status = result if isinstance(result, tuple) else (result, 200)
            return response.get_json(), status
    base = {"_response": "json", "name": "New colored washer", "buy_price": "100", "sale_price": "150",
            "has_colors": "1", "color_name[]": ["أبيض", "أسود"], "color_qty[]": ["3", "2"],
            "color_images": json.dumps([{"name": "أسود", "field": "color_image_0"}])}
    count = Product.query.count()
    body, status = create({**base, "color_image_0": (BytesIO(b"invalid"), "invalid.png")})
    assert status == 400, body
    assert Product.query.count() == count and not list(folder.rglob("color_*.webp"))
    body, status = create({**base, "color_image_0": (png("black"), "black.png")})
    assert status == 200, body
    created = Product.query.get(body["product_id"])
    assert Product.query.count() == count + 1 and created.quantity == created.opening_stock == 5
    colors = {row["name"]: row for row in get_product_colors(created.id)}
    assert colors["أسود"]["qty"] == 2 and colors["أسود"]["image_url"]


def test_store_cards_and_cart_use_selected_color_photo(media, monkeypatch):
    from flask import current_app
    from modules.storefront.services.product_presenter import product_card
    from modules.storefront.services.cart_service import StorefrontCartService
    import modules.storefront.services.cart_service as cart_module
    product, _, update, _, _ = media
    body, status = photos(update, [{"name": "أبيض", "field": "color_image_0"}], color_image_0=(png(), "white.png"))
    assert status == 200, body
    with current_app.test_request_context("/shop/test/product/1"):
        card = product_card(product, "test")
        assert card["image_url"] == card["colors"][0]["image_url"]
        html = current_app.jinja_env.get_template("storefront/_color_picker.html").render(product=card)
        assert 'data-sf-color="أبيض"' in html and card["image_url"] in html
        monkeypatch.setattr(cart_module, "cash_store_product_is_visible", lambda _: True)
        monkeypatch.setattr(cart_module, "published_installment_item", lambda _: None)
        cart = StorefrontCartService("test")
        # Use the same key formatter as the cart, preserving its current contract.
        key = cart._line_key(product.id, "أبيض", "normal", None)
        monkeypatch.setattr(cart, "cart_raw", lambda: {key: 1})
        items = cart.items()
        assert len(items) == 1 and items[0]["image_url"] == card["image_url"]
        # Render the actual store template for a browser test, using synthetic data only.
        import base64
        def picture(color):
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500"><rect width="500" height="500" fill="#f3f1fa"/><rect x="120" y="60" width="260" height="380" rx="18" fill="{color}" stroke="#8d8aa0" stroke-width="3"/><circle cx="250" cy="280" r="90" fill="#747789"/><circle cx="250" cy="280" r="65" fill="#b9c5d7"/><rect x="150" y="95" width="150" height="20" rx="8" fill="#b9c5d7"/></svg>'
            return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        card.update(name="غسالة FINORA — معاينة الألوان", stock=8, is_available=True,
                    image_url=picture("#d2d0dd"), gallery=[picture("#d2d0dd"), picture("#bfcde6")],
                    colors=[{"name": "أبيض", "qty": 4, "image_url": picture("#ffffff")},
                            {"name": "أسود", "qty": 4, "image_url": picture("#292633")},
                            {"name": "فضي", "qty": 0, "image_url": ""}])
        from modules.storefront.services.settings_service import StorefrontSettingsService
        design = StorefrontSettingsService().design_settings()
        design.update(store_name="FINORA", primary_color="#7645ed", ai_assistant_enabled=False)
        html = current_app.jinja_env.get_template("storefront/product_detail.html").render(
            product=card, related_products=[], store_design=design, shop_tenant_slug="test", cart_count=0,
            store_account=None, favorite_ids=[], favorite_count=0, store_sale_products=[card], help_fields_json="{}", current_year=2026)
        (Path(__file__).resolve().parent / "_artifacts").mkdir(parents=True, exist_ok=True)
        (Path(__file__).resolve().parent / "_artifacts" / "color-photo-store-preview.html").write_text(html, encoding="utf-8")
