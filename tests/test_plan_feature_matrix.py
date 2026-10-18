from utils.plan_limits import (
    PLAN_FEATURE_LABELS,
    resolve_plan_features,
)
from utils.tenant_feature_flags import TENANT_FEATURE_LABELS


def test_old_free_plan_row_gets_every_operational_page():
    features = resolve_plan_features(
        "free",
        {"inventory": True, "ai_assistant": False},
    )

    assert set(TENANT_FEATURE_LABELS).issubset(features)
    assert features["dashboard"] is True
    assert features["purchases"] is True
    assert features["supplier_statement"] is True
    assert features["notes"] is True
    assert features["installments_contracts"] is True
    assert features["reports_daily"] is True
    assert features["ai_assistant"] is False
    assert features["assistant_chat"] is False
    assert features["ai_workspace"] is False


def test_explicit_page_setting_wins_over_parent_and_legacy_defaults():
    features = resolve_plan_features(
        "basic",
        {
            "reports_adv": False,
            "reports_daily": True,
            "ai_sales": True,
            "trade_in_sales": True,
        },
    )

    assert features["reports"] is False
    assert features["reports_daily"] is True
    assert features["ai_sales"] is True
    assert features["trade_in_sales"] is True


def test_quick_sale_is_independent_from_pos():
    features = resolve_plan_features(
        "basic",
        {
            "pos": False,
        },
    )

    assert features["pos"] is False
    assert features["quick_sale"] is True


def test_plan_editor_catalog_contains_all_company_pages():
    assert set(TENANT_FEATURE_LABELS).issubset(PLAN_FEATURE_LABELS)
    assert "ai_sales" in PLAN_FEATURE_LABELS
    assert "notes" in PLAN_FEATURE_LABELS
    assert "installments_settings" in PLAN_FEATURE_LABELS
    assert "reports_adv" in PLAN_FEATURE_LABELS
    assert "rbac" in PLAN_FEATURE_LABELS
