import json
from datetime import date

import pytest

from modules.installments.services import InstallmentCalculationService, InstallmentError, add_months


def plan(**overrides):
    value = {
        "months": 12,
        "pricing_mode": "percentage",
        "markup_percentage": "20",
        "fixed_total_price": None,
        "fixed_monthly_amount": None,
        "down_payment_type": "none",
        "down_payment_value": "0",
        "processing_fee": 0,
    }
    value.update(overrides)
    return value


def test_percentage_markup_is_exact():
    result = InstallmentCalculationService.calculate(500_000, plan())
    assert result.installment_total == 600_000
    assert result.markup_amount == 100_000
    assert result.monthly_payment == 50_000
    assert sum(row["amount"] for row in result.schedule) == 600_000


def test_fixed_total_and_percentage_down_payment():
    result = InstallmentCalculationService.calculate(
        500_000,
        plan(pricing_mode="fixed_total", fixed_total_price=600_000, down_payment_type="percentage", down_payment_value="20"),
    )
    assert result.down_payment == 120_000
    assert result.financed_amount == 480_000
    assert result.monthly_payment == 40_000


def test_fixed_monthly_and_fixed_down_payment():
    result = InstallmentCalculationService.calculate(
        400_000,
        plan(months=9, pricing_mode="fixed_monthly", fixed_monthly_amount=50_000, down_payment_type="fixed", down_payment_value=45_000),
    )
    assert result.installment_total == 450_000
    assert result.financed_amount == 405_000
    assert result.monthly_payment == 45_000


def test_rounding_difference_is_assigned_to_final_installment():
    result = InstallmentCalculationService.calculate(
        100,
        plan(months=3, pricing_mode="fixed_total", fixed_total_price=100),
    )
    assert [row["amount"] for row in result.schedule] == [33, 33, 34]
    assert result.down_payment + sum(row["amount"] for row in result.schedule) == result.installment_total


def test_fees_are_included_without_floating_point_loss():
    result = InstallmentCalculationService.calculate(
        499_999,
        plan(months=7, markup_percentage="17.25", processing_fee=2_500),
    )
    assert result.installment_total == 588_749
    assert result.fees == 2_500
    assert result.down_payment + sum(row["amount"] for row in result.schedule) == result.installment_total


@pytest.mark.parametrize(
    "bad_plan",
    [
        plan(months=0),
        plan(pricing_mode="unknown"),
        plan(down_payment_type="percentage", down_payment_value=101),
        plan(pricing_mode="fixed_total", fixed_total_price=99),
    ],
)
def test_invalid_plans_are_rejected(bad_plan):
    with pytest.raises(InstallmentError):
        InstallmentCalculationService.calculate(100, bad_plan)


def test_add_months_handles_end_of_month_and_leap_year():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


@pytest.mark.parametrize("raw,canonical", [
    ("0770 123 4567", "07701234567"),
    ("+964 770 123 4567", "07701234567"),
    ("00964-770-123-4567", "07701234567"),
])
def test_iraqi_phone_normalization(raw, canonical):
    from modules.installments.services import normalize_phone

    assert normalize_phone(raw) == canonical


def test_application_status_transitions_are_restricted():
    from modules.installments.services import InstallmentError, validate_application_transition

    validate_application_transition("new", "under_review")
    with pytest.raises(InstallmentError):
        validate_application_transition("new", "completed")


def test_map_url_accepts_https_only():
    from modules.installments.routes import _sanitize_map_url

    assert _sanitize_map_url("https://maps.google.com/?q=Baghdad") == "https://maps.google.com/?q=Baghdad"
    assert _sanitize_map_url("javascript:alert(1)") is None
    assert _sanitize_map_url("   ") is None


def test_blueprints_expose_required_module_pages():
    from flask import Flask
    from modules.installments import init_installments

    app = Flask(__name__)
    init_installments(app)
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/installment-store/<tenant_slug>/<slug>" in rules
    assert "/installment-store/<tenant_slug>/product/<slug>" in rules
    assert "/supermax/<slug>" in rules
    assert "/installments/applications/<int:application_id>" in rules
    assert "/installments/contracts/<int:contract_id>/print" in rules
    assert "/installments/customers/<int:customer_id>/statement" in rules
    assert "/installments/api/products/quick-create" in rules
    assert "/installments/api/products/<int:product_id>/ad-kit" in rules
    assert "/installments/api/products/<int:product_id>/ad-copy" in rules
    assert "/installments/api/products/<int:product_id>/publish-facebook" in rules
    assert "/installment-store/<tenant_slug>/cart/update" in rules
    assert "/installment-store/<tenant_slug>/account" in rules
    assert "/installment-store/<tenant_slug>/account/register" in rules
    assert "/installment-store/<tenant_slug>/account/login" in rules
    assert "/installment-store/<tenant_slug>/favorites" in rules
    assert "/installment-store/<tenant_slug>/favorites/<int:product_id>" in rules


def test_facebook_multi_photo_post_attaches_selected_images(monkeypatch, tmp_path):
    from modules.publisher.services import facebook_service

    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/photos"):
            return {"success": True, "data": {"id": f"photo-{len(calls)}"}}
        return {"success": True, "data": {"id": "page-post"}}

    monkeypatch.setattr(facebook_service, "_retry_post", fake_post)
    result = facebook_service.publish_multi_photo_post(
        "page-1",
        "page-token",
        "نص المنشور",
        [str(first), str(second)],
    )

    assert result["success"] is True
    assert result["media_count"] == 2
    assert len(calls) == 3
    feed_payload = calls[-1][1]["data"]
    assert json.loads(feed_payload["attached_media[0]"]) == {"media_fbid": "photo-1"}
    assert json.loads(feed_payload["attached_media[1]"]) == {"media_fbid": "photo-2"}


def test_cross_site_mutations_are_rejected():
    from flask import Flask
    from modules.installments.routes import _csrf_guard

    app = Flask(__name__)
    with app.test_request_context("/installment-store/demo/cart", method="POST", headers={"Sec-Fetch-Site": "cross-site"}):
        response, status = _csrf_guard()
        assert status == 403
        assert response.get_json()["code"] == "CSRF_REJECTED"


def test_product_specs_keep_comma_separated_values_together_and_split_bullets():
    from modules.installments.routes import _parse_product_specs

    specs = _parse_product_specs(
        "سعة كبيرة تصل إلى 15 طقم صحون • تحتوي على 6 برامج غسيل مختلفة • "
        "البرامج تشمل: مكثف، اقتصادي ECO، خفيف، 60 دقيقة، سريع • "
        "كفاءة طاقة A+++ لاستهلاك كهرباء أقل. تجفيف Turbo Fan لتجفيف أفضل"
    )

    assert specs["rows"] == [{
        "label": "البرامج تشمل",
        "value": "مكثف، اقتصادي ECO، خفيف، 60 دقيقة، سريع",
    }]
    assert specs["features"] == [
        "سعة كبيرة تصل إلى 15 طقم صحون",
        "تحتوي على 6 برامج غسيل مختلفة",
        "كفاءة طاقة A+++ لاستهلاك كهرباء أقل",
        "تجفيف Turbo Fan لتجفيف أفضل",
    ]
    assert all("•" not in value for value in specs["features"])


def test_legacy_inventory_product_without_tenant_id_can_be_added(monkeypatch):
    from flask import session
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentProduct
    import modules.installments.routes as routes

    app = _make_app()
    payload = {
        "product_id": 1,
        "title": "شاشة ذكية",
        "slug": "smart-tv",
        "cash_price": 500_000,
        "status": "draft",
        "plans": [{
            "months": 12,
            "pricing_mode": "percentage",
            "markup_percentage": 10,
            "down_payment_type": "none",
            "down_payment_value": 0,
            "processing_fee": 0,
            "active": True,
        }],
    }
    with app.test_request_context("/installments/api/products", method="POST", json=payload):
        tenant = Tenant(id=1, name="Legacy Shop")
        product = Product(id=1, tenant_id=None, name="Legacy TV", buy_price=300_000, sale_price=500_000, quantity=4, active=True)
        db.session.add_all([tenant, product])
        db.session.commit()
        session["tenant_id"] = tenant.id
        monkeypatch.setattr(routes, "_guard_installment", lambda *args, **kwargs: None)

        response = routes.create_product()

        assert response.status_code == 200
        created = InstallmentProduct.query.one()
        assert created.tenant_id == tenant.id
        assert created.product_id == product.id
        assert created.plans[0].months == 12


def test_quick_product_creation_builds_inventory_store_and_auto_codes(monkeypatch):
    from flask import session
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentProduct
    import modules.installments.routes as routes

    app = _make_app()
    payload = {
        "name": "ثلاجة Samsung سعة 18 قدم",
        "brand": "Samsung",
        "buy_price": 500_000,
        "profit_percentage": 20,
        "sale_price": 600_000,
        "opening_stock": 3,
        "months": 12,
        "installment_markup": 10,
        "publish_to_store": True,
    }
    with app.app_context():
        tenant = Tenant(id=1, name="Quick Product Shop")
        branch = Branch(code="BGD", name="فرع بغداد", is_active=True, is_default=True)
        db.session.add_all([tenant, branch])
        db.session.commit()
        tenant_id = tenant.id
        branch_id = branch.id
    payload["branch_id"] = branch_id

    with app.test_request_context("/installments/api/products/quick-create", method="POST", json=payload):
        session["tenant_id"] = tenant_id
        monkeypatch.setattr(routes, "_guard_installment", lambda *args, **kwargs: None)

        response = routes.quick_create_product()

        assert response.status_code == 200
        result = response.get_json()
        source = Product.query.one()
        storefront = InstallmentProduct.query.one()
        assert source.tenant_id == tenant_id
        assert source.sku == result["sku"]
        assert len(source.barcode) == 13 and source.barcode.isdigit()
        assert source.buy_price == 500_000
        assert source.sale_price == 600_000
        assert source.quantity == 3
        assert source.catalog_category == "أجهزة منزلية"
        assert BranchStock.query.filter_by(branch_id=branch_id, product_id=source.id).one().quantity == 3
        assert storefront.product_id == source.id
        assert storefront.status == "published"
        assert storefront.category == "أجهزة منزلية"
        assert storefront.plans[0].months == 12


def test_product_name_category_inference_has_safe_fallback():
    from modules.installments.routes import _infer_product_category

    assert _infer_product_category("لابتوب Dell Latitude") == ("حواسيب ولابتوبات", "لابتوبات")
    assert _infer_product_category("منتج غير معروف") == ("أخرى", "منتجات متنوعة")


def test_ad_copy_has_editable_fallback_when_ai_is_unavailable(monkeypatch):
    from modules.ai_sales import openai_service
    from modules.installments.ad_service import generate_ad_creative

    monkeypatch.setattr(openai_service, "get_openai_api_key", lambda: "")
    creative = generate_ad_creative(
        {
            "title": "ثلاجة سامسونج 18 قدم",
            "cash_price": 750_000,
            "max_months": 12,
            "store_url": "https://example.test/product/fridge",
            "category": "ثلاجات",
        },
        platform="facebook",
    )

    assert creative["ai_generated"] is False
    assert "ثلاجة سامسونج" in creative["primary_text"]
    assert "12 شهر" in creative["primary_text"]
    assert creative["platform"] == "facebook"
    assert creative["warning"]


def test_meta_ads_launch_url_points_to_ads_manager():
    from modules.installments.ad_service import PLATFORM_CONFIG

    assert PLATFORM_CONFIG["facebook"]["launch_url"] == "https://adsmanager.facebook.com/adsmanager/creation/"
    assert PLATFORM_CONFIG["instagram"]["launch_url"] == "https://adsmanager.facebook.com/adsmanager/creation/"


def test_ad_copy_uses_structured_responses_api(monkeypatch):
    from modules.ai_sales import openai_service
    from modules.installments.ad_service import generate_ad_creative

    captured = {}
    payload = {
        "primary_text": "نص الإعلان",
        "headline": "عنوان",
        "description": "وصف",
        "call_to_action": "تسوّق الآن",
        "hashtags": ["#العراق"],
        "search_headlines": ["عنوان بحث"],
        "search_descriptions": ["وصف بحث"],
        "keywords": ["تقسيط"],
        "video_hook": "افتتاحية",
        "video_script": "سيناريو",
        "visual_direction": "الصورة الرئيسية أولاً",
    }

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    fake_client = type("Client", (), {"responses": FakeResponses()})()
    monkeypatch.setattr(openai_service, "get_openai_api_key", lambda: "configured")
    monkeypatch.setattr(openai_service, "get_openai_client", lambda: fake_client)
    app = _make_app()
    with app.app_context():
        creative = generate_ad_creative({"title": "غسالة", "cash_price": 500_000}, platform="instagram")

    assert creative["ai_generated"] is True
    assert creative["primary_text"] == "نص الإعلان"
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["reasoning"]["effort"] == "low"


def test_sensitive_actions_require_rbac(monkeypatch):
    import modules.installments.routes as routes

    monkeypatch.setattr(routes, "check_permission", lambda _name: False)
    monkeypatch.setattr(routes, "guard_permission", lambda name, json=None: (name, 403))
    assert routes._guard_installment("approve_installment_applications", "installments.applications.approve", json_response=True)[1] == 403
    assert routes._guard_installment("collect_installment_payments", "installments.payments.create", json_response=True)[1] == 403


def _make_app():
    from flask import Flask
    from extensions import db

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test", SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    import models  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import models.page  # noqa: F401
    import models.user  # noqa: F401
    import models.system_settings  # noqa: F401
    import modules.installments.models  # noqa: F401
    with app.app_context():
        db.create_all()
    return app


def test_allowed_durations_reject_plan_creation_filter_cards_and_disable_old_plans(monkeypatch):
    from flask import session
    from extensions import db
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentPlan, InstallmentProduct, InstallmentSettings
    import modules.installments.routes as routes

    app = _make_app()
    with app.test_request_context("/"):
        tenant = Tenant(name="Duration Rules Test")
        db.session.add(tenant)
        db.session.flush()
        product = Product(
            tenant_id=tenant.id,
            name="Washing Machine",
            buy_price=300_000,
            sale_price=500_000,
            quantity=4,
            active=True,
        )
        db.session.add(product)
        db.session.flush()
        item = InstallmentProduct(
            tenant_id=tenant.id,
            product_id=product.id,
            title="Washing Machine",
            slug="duration-rules-washer",
            cash_price=500_000,
            status="published",
        )
        db.session.add(item)
        db.session.flush()
        db.session.add_all([
            InstallmentSettings(tenant_id=tenant.id, allowed_durations_json="[3, 6, 9, 12]"),
            InstallmentPlan(
                tenant_id=tenant.id,
                installment_product_id=item.id,
                months=10,
                pricing_mode="percentage",
                markup_percentage=10,
                down_payment_type="none",
                active=True,
            ),
            InstallmentPlan(
                tenant_id=tenant.id,
                installment_product_id=item.id,
                months=12,
                pricing_mode="percentage",
                markup_percentage=10,
                down_payment_type="none",
                active=True,
            ),
        ])
        db.session.commit()

        with pytest.raises(InstallmentError, match="غير مسموحة"):
            routes._parse_plan(plan(months=10, cash_price=500_000), tenant.id, item.id)

        allowed_plan = routes._parse_plan(plan(months=12, cash_price=500_000), tenant.id, item.id)
        assert allowed_plan.months == 12
        assert [row.months for row in routes._store_card(item)["plans"]] == [12]

        monkeypatch.setattr(routes, "_guard_installment", lambda *args, **kwargs: None)
        monkeypatch.setattr(routes, "url_for", lambda *args, **kwargs: "/installments/settings")
        with app.test_request_context(
            "/installments/settings",
            method="POST",
            data={"allowed_durations": "3, 6, 9, 12"},
        ):
            session["tenant_id"] = tenant.id
            response = routes.settings_page()
            plans_by_month = {row.months: row for row in InstallmentPlan.query.order_by(InstallmentPlan.months).all()}
            assert response.status_code == 302
            assert plans_by_month[10].active is False
            assert plans_by_month[12].active is True
            assert set(plans_by_month) == {3, 6, 9, 10, 12}
            monthly_payments = {
                month: InstallmentCalculationService.calculate(item.cash_price, plans_by_month[month]).monthly_payment
                for month in (3, 6, 9, 12)
            }
            assert len(set(monthly_payments.values())) == 4
            assert monthly_payments[3] > monthly_payments[6] > monthly_payments[9] > monthly_payments[12]

            legacy_product = Product(
                tenant_id=tenant.id,
                name="Legacy Refrigerator",
                buy_price=300_000,
                sale_price=500_000,
                quantity=2,
                active=True,
            )
            db.session.add(legacy_product)
            db.session.flush()
            legacy_item = InstallmentProduct(
                tenant_id=tenant.id,
                product_id=legacy_product.id,
                title="Legacy Refrigerator",
                slug="legacy-duration-refrigerator",
                cash_price=500_000,
                status="published",
            )
            db.session.add(legacy_item)
            db.session.flush()
            db.session.add(InstallmentPlan(
                tenant_id=tenant.id,
                installment_product_id=legacy_item.id,
                months=10,
                pricing_mode="percentage",
                markup_percentage=10,
                down_payment_type="none",
                active=False,
            ))
            db.session.commit()

            assert routes._ensure_allowed_duration_plans(tenant.id, legacy_item.id) is True
            repaired_months = {
                row.months
                for row in InstallmentPlan.query.filter_by(installment_product_id=legacy_item.id, active=True).all()
            }
            assert repaired_months == {3, 6, 9, 12}
            assert routes._store_card(legacy_item)["plans"]


def test_schema_and_application_idempotency():
    from extensions import db
    from sqlalchemy import inspect
    from models.customer import Customer
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentApplication, InstallmentPlan, InstallmentProduct
    from modules.installments.services import ApplicationService

    app = _make_app()
    with app.test_request_context("/"):
        assert "installment_contract_items" in inspect(db.engine).get_table_names()
        tenant = Tenant(name="Installment Test")
        db.session.add(tenant)
        db.session.flush()
        product = Product(tenant_id=tenant.id, name="Device", buy_price=200_000, sale_price=500_000, quantity=0, active=True)
        existing_customer = Customer(tenant_id=tenant.id, name="عميل موجود", phone="+964 770 123 4567")
        db.session.add_all([product, existing_customer])
        db.session.flush()
        item = InstallmentProduct(tenant_id=tenant.id, product_id=product.id, title="Device", slug="device", cash_price=500_000, status="published")
        db.session.add(item)
        db.session.flush()
        installment_plan = InstallmentPlan(tenant_id=tenant.id, installment_product_id=item.id, months=12, pricing_mode="percentage", markup_percentage=20, down_payment_type="percentage", down_payment_value=20, processing_fee=0, active=True)
        db.session.add(installment_plan)
        db.session.commit()
        form = {"customer_name": "أحمد محمد علي حسن", "phone": "07701234567", "city": "بغداد", "address": "شارع 10", "quantity": 1}
        first, token = ApplicationService.create(item, installment_plan, form, "idempotency-key-123456")
        second, duplicate_token = ApplicationService.create(item, installment_plan, form, "idempotency-key-123456")
        assert first.id == second.id
        assert product.quantity == 0
        assert first.application_number.endswith("-000001")
        assert first.customer_id == existing_customer.id
        assert existing_customer.name == "أحمد محمد علي حسن"
        assert existing_customer.phone == "07701234567"
        assert existing_customer.city == "بغداد"
        assert existing_customer.address == "شارع 10"
        assert Customer.query.count() == 1
        assert token
        assert duplicate_token == ""
        assert ApplicationService.tracked(token, form["phone"], tenant.id).id == first.id
        assert ApplicationService.tracked(token, form["phone"], tenant.id + 999) is None
        assert InstallmentApplication.query.count() == 1
        assert json.loads(first.items[0].calculation_json)["installment_total"] == 600_000
        assert first.items[0].months_snapshot == 12
        installment_plan.active = False
        db.session.commit()
        with pytest.raises(InstallmentError):
            ApplicationService.create(item, installment_plan, form, "disabled-plan-key-123")
        installment_plan.active = True
        item.status = "disabled"
        db.session.commit()
        with pytest.raises(InstallmentError):
            ApplicationService.create(item, installment_plan, form, "disabled-product-key-123")


def test_customer_account_registration_and_login_are_secure(monkeypatch):
    import secrets
    from flask import g, session
    from werkzeug.security import check_password_hash
    from extensions import db
    from models.customer import Customer
    from models.tenant import Tenant
    from modules.installments import init_installments
    from modules.installments.models import InstallmentCustomerAccount
    from modules.installments.schema import ensure_installment_schema
    import modules.installments.routes as routes

    app = _make_app()
    init_installments(app)
    monkeypatch.setattr(routes, "allow_request", lambda *args, **kwargs: True)
    password = "strong-pass-2026"
    phone = f"0770{secrets.randbelow(10_000_000):07d}"
    with app.test_request_context(
        "/installment-store/account-shop/account/register",
        method="POST",
        json={"name": "أحمد محمد علي حسن", "phone": phone, "password": password},
    ):
        g.tenant = "account-shop"
        ensure_installment_schema()
        tenant = Tenant.query.filter_by(subdomain="account-shop").first()
        if not tenant:
            tenant = Tenant(name="Account Shop", subdomain="account-shop")
            db.session.add(tenant)
            db.session.commit()
        tenant_id = tenant.id
        g.installment_tenant_id = tenant_id
        response, status = routes.account_register("account-shop")
        assert status == 201
        account = InstallmentCustomerAccount.query.filter_by(phone=phone).one()
        customer = Customer.query.get(account.customer_id)
        assert account.customer_id == customer.id
        assert account.phone == phone
        assert account.password_hash != password
        assert check_password_hash(account.password_hash, password)
        assert session[routes._customer_account_key("account-shop")] == account.id
        account_id = account.id

    with app.test_request_context(
        "/installment-store/account-shop/account/login",
        method="POST",
        json={"phone": phone, "password": password},
    ):
        g.tenant = "account-shop"
        g.installment_tenant_id = tenant_id
        response = routes.account_login("account-shop")
        assert response.get_json()["success"] is True
        assert session[routes._customer_account_key("account-shop")] == account_id


def test_store_favorite_toggle_persists_in_session(monkeypatch):
    from types import SimpleNamespace
    from flask import session
    import modules.installments.routes as routes

    app = _make_app()
    item = SimpleNamespace(id=9, status="published")
    monkeypatch.setattr(
        routes,
        "_scoped",
        lambda model, tenant_id=None: SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: item)),
    )
    with app.test_request_context("/", method="POST", headers={"Accept": "application/json"}, json={}):
        added = routes.favorite_toggle("fav-shop", item.id)
        payload = added.get_json()
        assert payload["success"] is True
        assert payload["favorited"] is True
        assert payload["count"] == 1
        assert session[routes._favorite_key("fav-shop")] == [item.id]

        removed = routes.favorite_toggle("fav-shop", item.id)
        removed_payload = removed.get_json()
        assert removed_payload["favorited"] is False
        assert removed_payload["count"] == 0
        assert session[routes._favorite_key("fav-shop")] == []

        session[routes._favorite_key("fav-shop")] = ["9", 9, 0, "bad", 12]
        assert routes._favorite_ids("fav-shop") == [9, 12]


def test_logged_in_order_identity_cannot_be_overridden():
    from types import SimpleNamespace
    import modules.installments.routes as routes

    account = SimpleNamespace(customer_id=17, phone="07700001111", customer=SimpleNamespace(name="زيد محمد علي حسن"))
    values = routes._account_order_data({"customer_name": "اسم مزور", "phone": "07799999999", "address": "عنوان جديد"}, account)
    assert values["_customer_id"] == 17
    assert values["customer_name"] == "زيد محمد علي حسن"
    assert values["phone"] == "07700001111"
    assert values["address"] == "عنوان جديد"


def test_schema_seeds_legacy_physical_tenant_row():
    from flask import g, session
    from models.tenant import Tenant
    from modules.installments.schema import ensure_installment_schema

    app = _make_app()
    with app.test_request_context("/"):
        g.tenant = "legacy-shop"
        session["tenant_id"] = 42
        session["tenant_slug"] = "legacy-shop"
        ensure_installment_schema()
        tenant = Tenant.query.get(42)
        assert tenant is not None
        assert tenant.subdomain == "legacy-shop"


def test_approval_contract_schedule_partial_payment_and_completion():
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import InstallmentPlan, InstallmentProduct, InstallmentSettings
    from modules.installments.services import ApplicationService, ApprovalService, PaymentService

    app = _make_app()
    with app.test_request_context("/"):
        tenant = Tenant(name="Lifecycle Test")
        db.session.add(tenant)
        db.session.flush()
        product = Product(tenant_id=tenant.id, name="Phone", buy_price=250_000, sale_price=500_000, quantity=2, active=True)
        branch = Branch(code="MAIN", name="Main", is_active=True, is_default=True)
        db.session.add_all([product, branch])
        db.session.flush()
        db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=2, opening_stock=2))
        item = InstallmentProduct(tenant_id=tenant.id, product_id=product.id, title="Phone", slug="phone", cash_price=500_000, status="published")
        db.session.add(item)
        db.session.flush()
        installment_plan = InstallmentPlan(tenant_id=tenant.id, installment_product_id=item.id, months=12, pricing_mode="percentage", markup_percentage=20, down_payment_type="percentage", down_payment_value=20, processing_fee=0, active=True)
        db.session.add_all([installment_plan, InstallmentSettings(tenant_id=tenant.id, enabled=True, payment_day=10, reservation_policy="on_delivery")])
        db.session.commit()

        application, _token = ApplicationService.create(item, installment_plan, {"customer_name": "علي كريم حسن جاسم", "phone": "07701112222", "city": "بغداد", "address": "الشارع الرئيسي"}, "lifecycle-idempotency-123")
        contract = ApprovalService.approve(application, None, date(2026, 8, 10))
        assert contract.total_amount == 600_000
        assert contract.down_payment == 120_000
        assert contract.remaining_amount == 480_000
        assert len(contract.schedules) == 12
        assert contract.first_due_date == date(2026, 9, 10)
        assert contract.schedules[0].remaining_amount == 40_000
        assert len(contract.items) == 1
        assert contract.items[0].product_name == "Phone"
        assert sum(row.amount for row in contract.schedules) == 480_000
        assert Product.query.get(product.id).quantity == 2
        assert Invoice.query.get(contract.invoice_id).source_module == "installments"
        assert db.session.query(db.func.sum(InvoicePaymentLedger.amount_delta)).filter_by(
            invoice_id=contract.invoice_id
        ).scalar() == 120_000
        ApprovalService.fulfill(contract, None)
        assert Product.query.get(product.id).quantity == 1
        assert Invoice.query.get(contract.invoice_id).stock_is_deducted is True

        partial = PaymentService.post(contract, 60_000, "cash", None)
        assert partial.amount == 60_000
        assert [allocation.amount for allocation in partial.allocations] == [40_000, 20_000]
        assert contract.schedules[0].status == "paid"
        assert contract.schedules[1].status == "partial"
        assert contract.remaining_amount == 420_000
        assert db.session.query(db.func.sum(InvoicePaymentLedger.amount_delta)).filter_by(
            invoice_id=contract.invoice_id
        ).scalar() == 180_000
        with pytest.raises(InstallmentError):
            PaymentService.post(contract, 420_001, "cash", None)

        final_payment = PaymentService.post(contract, 420_000, "cash", None)
        assert contract.remaining_amount == 0
        assert contract.status == "completed"
        assert all(row.status == "paid" for row in contract.schedules)
        assert db.session.query(db.func.sum(InvoicePaymentLedger.amount_delta)).filter_by(
            invoice_id=contract.invoice_id
        ).scalar() == 600_000
        with pytest.raises(InstallmentError):
            PaymentService.post(contract, 1, "cash", None)
        reversal = PaymentService.reverse(final_payment, None, "Test correction")
        assert reversal.status == "reversal"
        assert final_payment.status == "reversed"
        assert contract.status == "active"
        assert contract.remaining_amount == 420_000
        assert db.session.query(db.func.sum(InvoicePaymentLedger.amount_delta)).filter_by(
            invoice_id=contract.invoice_id
        ).scalar() == 180_000
        with pytest.raises(InstallmentError):
            PaymentService.reverse(final_payment, None, "Again")


def test_order_cancellation_synchronizes_installment_application_and_contract():
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from models.tenant import Tenant
    from modules.installments.models import (
        InstallmentApplicationActivity,
        InstallmentPlan,
        InstallmentProduct,
        InstallmentSettings,
    )
    from modules.installments.services import ApplicationService, ApprovalService
    from utils.order_lifecycle import process_order_cancel

    app = _make_app()
    with app.test_request_context("/"):
        tenant = Tenant(name="Cancellation Sync Test")
        db.session.add(tenant)
        db.session.flush()
        product = Product(
            tenant_id=tenant.id,
            name="Television",
            buy_price=250_000,
            sale_price=500_000,
            quantity=2,
            active=True,
        )
        branch = Branch(code="CANCEL", name="Cancellation Branch", is_active=True, is_default=True)
        db.session.add_all([product, branch])
        db.session.flush()
        branch_stock = BranchStock(branch_id=branch.id, product_id=product.id, quantity=2, opening_stock=2)
        item = InstallmentProduct(
            tenant_id=tenant.id,
            product_id=product.id,
            title="Television",
            slug="television-cancel",
            cash_price=500_000,
            status="published",
        )
        db.session.add_all([branch_stock, item])
        db.session.flush()
        installment_plan = InstallmentPlan(
            tenant_id=tenant.id,
            installment_product_id=item.id,
            months=10,
            pricing_mode="percentage",
            markup_percentage=10,
            down_payment_type="none",
            down_payment_value=0,
            processing_fee=0,
            active=True,
        )
        db.session.add_all([
            installment_plan,
            InstallmentSettings(
                tenant_id=tenant.id,
                enabled=True,
                payment_day=10,
                reservation_policy="on_approval",
            ),
        ])
        db.session.commit()

        application, _token = ApplicationService.create(
            item,
            installment_plan,
            {
                "customer_name": "سجاد احمد فالح صالح",
                "phone": "07734049148",
                "city": "بغداد",
                "address": "الأمينة الثانية",
            },
            "cancel-sync-idempotency-123",
        )
        contract = ApprovalService.approve(application, None, date(2026, 8, 10))
        invoice = contract.invoice
        assert Product.query.get(product.id).quantity == 1
        assert BranchStock.query.get(branch_stock.id).quantity == 1

        process_order_cancel(invoice, reason="طلب الزبون إلغاء الطلب")
        db.session.commit()

        assert invoice.status == "ملغي"
        assert invoice.payment_status == "ملغي"
        assert application.status == "cancelled"
        assert contract.status == "cancelled"
        assert contract.paid_amount == 0
        assert contract.remaining_amount == 0
        assert all(schedule.status == "cancelled" for schedule in contract.schedules)
        assert all(schedule.remaining_amount == 0 for schedule in contract.schedules)
        assert Product.query.get(product.id).quantity == 2
        assert BranchStock.query.get(branch_stock.id).quantity == 2
        assert InstallmentApplicationActivity.query.filter_by(
            application_id=application.id,
            action="cancelled_from_order",
        ).count() == 1

        # Retrying an already-cancelled legacy order repairs linked records but
        # must not return inventory or duplicate history a second time.
        process_order_cancel(invoice, reason="إعادة مزامنة")
        db.session.commit()
        assert Product.query.get(product.id).quantity == 2
        assert BranchStock.query.get(branch_stock.id).quantity == 2
        assert InstallmentApplicationActivity.query.filter_by(
            application_id=application.id,
            action="cancelled_from_order",
        ).count() == 1
