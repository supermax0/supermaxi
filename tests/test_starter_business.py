"""Regression coverage for the lightweight starter-business activity."""

from pathlib import Path


def test_starter_business_is_a_supported_company_type():
    from routes.superadmin import BUSINESS_TYPES, _clean_business_type

    assert _clean_business_type("starter_business") == "starter_business"
    assert BUSINESS_TYPES["starter_business"] == "إدارة أعمال مبسّطة"
    assert _clean_business_type("unknown-type") == "general"


def test_starter_business_feature_defaults_and_overrides_are_independent():
    from utils.starter_business import allows
    from utils.tenant_feature_flags import default_feature_enabled, normalize_feature_overrides

    assert default_feature_enabled("orders", business_type="starter_business")
    assert default_feature_enabled("inventory_add_product", business_type="starter_business")
    assert default_feature_enabled("purchases", business_type="starter_business")
    assert default_feature_enabled("suppliers", business_type="starter_business")
    assert default_feature_enabled("receipts", business_type="starter_business")
    assert default_feature_enabled("reports_profit", business_type="starter_business")
    assert not default_feature_enabled("pos", business_type="starter_business")
    assert not default_feature_enabled("notes", business_type="starter_business")
    assert not default_feature_enabled("executive_dashboard", business_type="starter_business")
    assert not default_feature_enabled("beauty", business_type="starter_business")
    assert default_feature_enabled("pos", business_type="general")
    assert default_feature_enabled("beauty", business_type="beauty_center")

    overrides = normalize_feature_overrides({"pos": True, "orders": False})
    assert overrides == {"pos": True, "orders": False}
    assert allows("pos", feature_overrides=overrides)
    assert not allows("orders", feature_overrides=overrides)
    # A company override can never bypass a feature disabled by its plan.
    assert not allows("pos", plan_features={"pos": False}, feature_overrides={"pos": True})


def test_starter_business_route_feature_mapping_keeps_core_and_specialized_routes_separate():
    from utils.starter_business import DEFAULT_FEATURES, feature_for_path

    assert feature_for_path("/orders/packed") == "orders_packed"
    assert feature_for_path("/inventory/add") == "inventory_add_product"
    assert feature_for_path("/reports/profit") == "reports_profit"
    assert feature_for_path("/beauty/services") == "beauty"
    assert feature_for_path("/purchases") == "purchases"
    assert feature_for_path("/suppliers") == "suppliers"
    assert feature_for_path("/receipts") == "receipts"
    assert feature_for_path("/notes") == "notes"
    assert feature_for_path("/inventory/transfers/new") == "stock_transfers"
    assert "orders" in DEFAULT_FEATURES
    assert "purchases" in DEFAULT_FEATURES
    assert "suppliers" in DEFAULT_FEATURES
    assert "receipts" in DEFAULT_FEATURES
    assert "notes" not in DEFAULT_FEATURES
    assert "executive_dashboard" not in DEFAULT_FEATURES
    assert "pos" not in DEFAULT_FEATURES


def test_starter_business_sidebar_menu_is_ordered_for_core_ops():
    template = (Path(__file__).resolve().parents[1] / "templates" / "base.html").read_text(encoding="utf-8")
    starter_block = template.split("{% if is_starter_business %}", 1)[1].split("{% else %}", 1)[0]

    assert "جميع الطلبات" in starter_block
    assert "المشتريات" in starter_block
    assert "الموردين" in starter_block
    assert "القبض والتسديدات" in starter_block
    assert "دفتر الملاحظات" not in starter_block
    assert "لوحة المدير التنفيذي" not in starter_block
    assert "not is_starter_business" in template


def test_superadmin_company_type_selector_includes_starter_business():
    template = (Path(__file__).resolve().parents[1] / "templates" / "tenant_list.html").read_text(encoding="utf-8")

    assert '<option value="starter_business">إدارة أعمال مبسّطة</option>' in template
