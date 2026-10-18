from pathlib import Path

from jinja2 import Environment

from modules.storefront.services.category_assets import category_image_path
from modules.storefront.services.category_normalize import merge_washer_category


ROOT = Path(__file__).resolve().parents[1]


def test_cash_and_installment_category_pages_use_shared_mosaic():
    cash = (ROOT / "templates/storefront/categories.html").read_text(encoding="utf-8")
    installment = (ROOT / "templates/installments/store/categories.html").read_text(encoding="utf-8")

    assert "store-category-showcase-page" in cash
    assert "is-mosaic" in cash
    assert "store-category-showcase-page" in installment
    assert "is-mosaic" in installment


def test_category_templates_and_responsive_mosaic_css_are_valid():
    environment = Environment()
    for relative in (
        "templates/storefront/categories.html",
        "templates/installments/store/categories.html",
    ):
        environment.parse((ROOT / relative).read_text(encoding="utf-8"))

    css = (ROOT / "static/css/installment_store.css").read_text(encoding="utf-8")
    assert ".store-category-page-grid.is-mosaic" in css
    assert "grid-auto-flow: dense" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 620px)" in css


def test_curated_category_images_cover_the_live_cash_store_categories():
    categories = (
        "أجهزة منزلية",
        "أخرى",
        "تكييف وتبريد",
        "ثلاجات",
        "شاشات",
        "غسالات",
        "مايكرويف",
        "مكانس",
    )

    for category in categories:
        relative_path = category_image_path(category)
        assert relative_path
        assert (ROOT / "static" / relative_path).is_file()


def test_washer_model_sections_merge_into_one_category():
    assert merge_washer_category("غسالة اريتون فول اوتوماتيك 18 كيلو موديل A18000") == "غسالات"
    assert merge_washer_category("غسالة حوضين هيتاشي 26 كيلو عادي") == "غسالات"
    assert merge_washer_category("غسالة ديكو حوضين 16 كيلو موديل 1600") == "غسالات"
    assert merge_washer_category("غسالات") == "غسالات"
    assert merge_washer_category("غسالة صحون كونكا الوان موديل 1400") == "غسالات صحون"
    assert merge_washer_category("غسالات صحون") == "غسالات صحون"
    assert merge_washer_category("أجهزة منزلية", "غسالة سامسونج") == "أجهزة منزلية"
    assert merge_washer_category("ثلاجات") == "ثلاجات"


def test_category_templates_prefer_curated_art_with_product_fallbacks():
    cash = (ROOT / "templates/storefront/categories.html").read_text(encoding="utf-8")
    installment = (ROOT / "templates/installments/store/categories.html").read_text(encoding="utf-8")

    assert "row.category_image" in cash
    assert "row.preview.image_url" in cash
    assert "row.category_image" in installment
    assert "row.preview and row.preview.main_media" in installment
