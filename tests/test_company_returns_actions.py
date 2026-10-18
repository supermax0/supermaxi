from pathlib import Path

from routes.shipping import company_returns_action_permission


def test_bulk_settlement_and_return_use_separate_permissions():
    assert company_returns_action_permission("settle") == "pay_orders"
    assert company_returns_action_permission(" SETTLE ") == "pay_orders"
    assert company_returns_action_permission("return") == "return_orders"
    assert company_returns_action_permission(None) == "return_orders"


def test_company_returns_page_exposes_both_actions():
    template = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "shipping_company_returns.html"
    ).read_text(encoding="utf-8")

    assert 'data-action="return"' in template
    assert 'data-action="settle"' in template
    assert "action:currentAction" in template
    assert "&action=${currentAction}" in template
    assert 'class="cr-delivery-fee"' in template
    assert "delivery_fee:Number(o.delivery_fee||0)" in template
