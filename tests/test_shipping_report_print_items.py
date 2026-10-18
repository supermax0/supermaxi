"""Unit tests for agent-report product rows used in professional print."""


def test_normalize_report_item_accepts_legacy_keys():
    from utils.agent_report_helpers import normalize_report_item

    item = normalize_report_item({"name": "قميص", "quantity": 2, "price": 50000})
    assert item["product_name"] == "قميص"
    assert item["quantity"] == 2
    assert item["total"] == 100000

    qty_item = normalize_report_item({"product": "لابتوب", "qty": 1})
    assert qty_item["product_name"] == "لابتوب"
    assert qty_item["quantity"] == 1


def test_shipping_report_print_template_renders_products_from_dict_rows():
    """Jinja dict.items must not shadow the products list (was causing HTTP 500)."""
    from datetime import datetime
    from pathlib import Path
    from types import SimpleNamespace

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    report = SimpleNamespace(
        id=83,
        report_number="AGT-1-20260813-0001",
        shipping_company_name="كشف المندوب: وسام رحيم",
        orders_count=1,
        created_at=datetime(2026, 8, 13, 10, 32),
        created_by="سوبر ماكس",
        is_executed=False,
    )
    orders_data = [
        {
            "id": 963,
            "customer_name": "مصطفى اسماعيل",
            "customer_phone": "07700745579",
            "customer_city": "بغداد",
            "customer_address": "الكرادة",
            "total": 195000,
            "paid_amount": 0,
            "remaining": 195000,
            "status": "جاري الشحن",
            "items": [
                {
                    "product_name": "قميص تجريبي",
                    "name": "قميص تجريبي",
                    "quantity": 2,
                    "price": 50000,
                    "total": 100000,
                }
            ],
            "products": [
                {
                    "product_name": "قميص تجريبي",
                    "name": "قميص تجريبي",
                    "quantity": 2,
                    "price": 50000,
                    "total": 100000,
                }
            ],
        }
    ]

    html = env.get_template("shipping_report_print.html").render(
        report=report,
        orders_data=orders_data,
        display_total_amount=195000,
        display_total_label="المجموع الكلي",
        items_count=1,
        items_qty=2,
        agent_label="وسام رحيم",
        company_name="سوبر ماكس",
        company_subtitle="للتجارة",
        report_logo=None,
        report_address="بغداد",
        report_phone="07700000000",
        report_footer="كشف رسمي",
        generated_at=datetime(2026, 8, 13, 13, 56),
        autoprint=False,
        is_public_access=False,
        access_token=None,
    )

    assert "قميص تجريبي" in html
    assert "963" in html
    assert "وسام رحيم" in html


def test_enrich_orders_data_items_normalizes_snapshot_without_live_db():
    from utils.agent_report_helpers import compute_report_items_totals, enrich_orders_data_items

    rows = enrich_orders_data_items(
        [
            {"id": 963, "products": [{"name": "لابتوب", "qty": 1, "price": 900000}]},
            {"id": 965, "items": [{"product_name": "سماعة", "quantity": 2, "price": 25000, "total": 50000}]},
        ],
        refresh_live=False,
    )

    assert rows[0]["items"][0]["product_name"] == "لابتوب"
    assert rows[0]["items"][0]["total"] == 900000
    assert rows[1]["items"][0]["name"] == "سماعة"
    totals = compute_report_items_totals(rows)
    assert totals["lines"] == 2
    assert totals["qty"] == 3
