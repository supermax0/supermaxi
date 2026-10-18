from extensions import db
from models.product import Product
from models.tenant import Tenant
from modules.installments.models import InstallmentProduct
from modules.storefront.services.cart_service import StorefrontCartService
from modules.storefront.services.product_presenter import product_card

from tests.test_installments import _make_app


def _published_zero_stock_product():
    tenant = Tenant(name="Reservation Store")
    db.session.add(tenant)
    db.session.flush()
    product = Product(
        tenant_id=tenant.id,
        name="Reserved washer",
        buy_price=300_000,
        sale_price=395_000,
        quantity=0,
        active=True,
        store_visible=True,
    )
    db.session.add(product)
    db.session.flush()
    db.session.add(
        InstallmentProduct(
            tenant_id=tenant.id,
            product_id=product.id,
            title=product.name,
            slug="reserved-washer",
            cash_price=395_000,
            status="published",
        )
    )
    db.session.commit()
    return product


def test_zero_stock_published_product_accepts_requested_quantity():
    app = _make_app()
    with app.test_request_context("/shop/super/"):
        product = _published_zero_stock_product()
        cart = StorefrontCartService("super")

        accepted, message = cart.try_add(product.id, 4)
        assert accepted is True
        assert "السلة" in message
        assert cart.count() == 4

        accepted_again, message_again = cart.try_add(product.id, 3)
        assert accepted_again is True
        assert "السلة" in message_again
        assert cart.count() == 7


def test_zero_stock_published_product_is_presented_as_reservation(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(
        "modules.storefront.services.product_presenter.url_for",
        lambda *args, **kwargs: f"/product/{kwargs['product_id']}",
    )
    with app.app_context():
        product = _published_zero_stock_product()
        item = InstallmentProduct.query.filter_by(product_id=product.id).one()
        card = product_card(product, "super", catalog_item=item)

        assert card["is_available"] is False
        assert card["is_reservation"] is True


def test_zero_stock_cart_quantity_can_be_changed_freely():
    app = _make_app()
    with app.test_request_context("/shop/super/"):
        product = _published_zero_stock_product()
        cart = StorefrontCartService("super")
        accepted, _message = cart.try_add(product.id, 1)
        assert accepted is True

        line_key = next(iter(cart.cart_raw()))
        updated, update_message = cart.try_update_quantities({line_key: 12})
        assert updated is True
        assert "تحديث السلة" in update_message
        assert cart.count() == 12
