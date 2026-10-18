from flask import Flask
from jinja2 import Environment, FileSystemLoader

from modules.workspace.routes import workspace_html_bp


def test_courier_print_route_and_template_are_available():
    app = Flask(__name__)
    app.register_blueprint(workspace_html_bp, url_prefix="/workspace")
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/workspace/courier-analysis/<analysis_id>/print" in rules

    template = Environment(
        loader=FileSystemLoader("templates"),
    ).get_template("workspace/courier_analysis_print.html")
    source = template.render(
        analysis=type("Analysis", (), {"id": "analysis-1"})(),
        rows=[],
        company_name="شركة الاختبار",
        company_address="بغداد",
        company_phone="07700000000",
        report_logo=None,
        courier_company="شركة النقل",
        generated_at=__import__("datetime").datetime(2026, 7, 29, 10, 0),
        report_number="ABC123",
        total_amount=100_000,
        total_fees=10_000,
        total_net=90_000,
        manual_exclusions=[],
    )
    assert "رقم الفاتورة" in source
    assert "باركود شركة النقل" in source
    assert "نسبة التطابق" in source
    assert "90,000" in source
    assert "size: A4 portrait" in source
