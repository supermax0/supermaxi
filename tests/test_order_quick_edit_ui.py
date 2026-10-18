from pathlib import Path


def test_order_details_exposes_stacked_quick_editor():
    template = (
        Path(__file__).resolve().parents[1] / "templates" / "orders.html"
    ).read_text(encoding="utf-8")

    assert "تعديل سريع" in template
    assert "modal oqe-overlay" in template
    assert "openQuickOrderEditor" in template
    assert "quickEditSearchProducts" in template
    assert "saveQuickOrderEditor" in template
    assert "'/orders/quick-edit/'" in template
    assert "oqeCustomerName" in template
    assert "oqeProductSearch" in template
    assert "oqeNote" in template
    assert "oqeDiscount" in template
