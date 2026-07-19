"""Regression tests for exact/nearest product selection and grounded prices."""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_sales_nearest_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def test_nearest_appliance_size_cheapest_screen_and_product_details():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from modules.ai_sales.engine import (
        _advertised_dollar_amount,
        _advertised_dollar_price_result,
        _direct_foot_size_result,
        _direct_size_price_result,
        _media_request_result,
        _price_flexibility_reply,
        _requested_product_media,
    )
    from modules.ai_sales.models import AISalesProductProfile
    from modules.ai_sales.product_tools import (
        find_nearest_smaller_foot_products,
        get_available_screen_products,
        search_products,
    )
    from modules.ai_sales.schema import ensure_ai_sales_schema

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_ai_sales_schema()
        fridge_5 = Product(
            name="ثلاجه شاربو 5قدم لون ابيض",
            buy_price=120_000,
            sale_price=145_000,
            quantity=4,
            active=True,
        )
        fridge_7 = Product(
            name="ثلاجه ايفولي 7قدم",
            buy_price=140_000,
            sale_price=169_000,
            quantity=3,
            active=True,
        )
        fridge_12 = Product(
            name="ثلاجه ايفولي 12قدم موديل 210W",
            buy_price=250_000,
            sale_price=289_000,
            quantity=2,
            active=True,
        )
        screen_cheap = Product(
            name="شاشه جنرال حجم 55",
            buy_price=300_000,
            sale_price=339_000,
            quantity=14,
            active=True,
        )
        screen_expensive = Product(
            name="شاشه ال جي حجم 55",
            buy_price=320_000,
            sale_price=349_000,
            quantity=4,
            active=True,
        )
        db.session.add_all([fridge_5, fridge_7, fridge_12, screen_cheap, screen_expensive])
        db.session.flush()
        db.session.add_all([
            ProductColorVariant(product_id=fridge_7.id, color_name="أبيض", quantity=2),
            ProductColorVariant(product_id=fridge_7.id, color_name="أسود", quantity=1),
            AISalesProductProfile(
                product_id=fridge_7.id,
                width_cm=52,
                height_cm=126,
                depth_cm=55,
            ),
        ])
        db.session.commit()

        six_foot = search_products("ثلاجه 6 قدم", limit=10)
        assert six_foot[0]["product_id"] == fridge_7.id
        assert six_foot[0]["colors"] == ["أبيض", "أسود"]
        assert six_foot[0]["dimensions"] == {
            "width_cm": 52.0,
            "height_cm": 126.0,
            "depth_cm": 55.0,
        }

        ten_foot = search_products("ثلاجه 10 قدم", limit=10)
        assert ten_foot[0]["product_id"] == fridge_12.id

        screens = get_available_screen_products(size=55, limit=10)
        assert [row["product_id"] for row in screens[:2]] == [screen_cheap.id, screen_expensive.id]
        screen_reply = _direct_size_price_result(list(reversed(screens)), 55)
        assert screen_reply["product_ids"] == [screen_cheap.id]
        assert "339,000 د.ع" in screen_reply["reply"]
        assert "349,000 د.ع" not in screen_reply["reply"]

        reply = _direct_foot_size_result(six_foot, 6, "اريد ثلاجه 6 قدم والابعاد")
        assert "6 قدم غير متوفر" in reply["reply"]
        assert "أقرب حجم موجود هو 7 قدم" in reply["reply"]
        assert "169,000 د.ع" in reply["reply"]
        assert "أبيض، أسود" in reply["reply"]
        assert "العرض 52" in reply["reply"]
        assert "المتوفر: 3" not in reply["reply"]

        smaller = find_nearest_smaller_foot_products(six_foot[0], limit=2)
        flexibility = _price_flexibility_reply(six_foot[0], smaller)
        assert "ثابت حالياً" in flexibility
        assert "5 قدم" in flexibility
        assert "145,000 د.ع" in flexibility

        assert _advertised_dollar_amount("انت ناشرها ب128") == 128
        advertised = _advertised_dollar_price_result(six_foot[0], 128)
        assert "128" in advertised["reply"]
        assert "بالدولار" in advertised["reply"]
        assert "169,000 د.ع" in advertised["reply"]

        assert _requested_product_media("عدك صوره للون الابيض") == "image"
        media_reply = _media_request_result(
            six_foot[0],
            "image",
            [{"public_url": "https://example.test/fridge-white.jpg"}],
            "عدك صوره للون الابيض",
        )
        assert "هاي الصورة للون الابيض" in media_reply["reply"]
        assert "ما عندي" not in media_reply["reply"]
        assert media_reply["product_ids"] == [fridge_7.id]


def test_product_family_filter_does_not_mix_appliances():
    from modules.ai_sales.engine import _product_matches_family

    assert _product_matches_family(
        {"official_name": "General Smart TV 55", "category": "screens"},
        "screen",
    )
    assert not _product_matches_family(
        {"official_name": "General Smart TV 55", "category": "screens"},
        "refrigerator",
    )
    assert _product_matches_family(
        {"official_name": "Fridge 7 feet", "category": "appliances"},
        "refrigerator",
    )
    assert not _product_matches_family(
        {"official_name": "Fridge 7 feet", "category": "appliances"},
        "screen",
    )
