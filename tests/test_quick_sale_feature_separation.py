from flask import Flask, session

import routes.quick_sale as quick_sale_routes


def _test_app():
    app = Flask(__name__)
    app.secret_key = "quick-sale-feature-test"
    return app


def test_disabled_quick_sale_redirects_only_its_page(monkeypatch):
    monkeypatch.setattr(
        quick_sale_routes,
        "tenant_feature_enabled",
        lambda feature: feature != "quick_sale",
    )

    with _test_app().test_request_context("/quick-sale/"):
        session["user_id"] = 1
        response = quick_sale_routes.quick_sale_feature_guard()

    assert response.status_code == 302
    assert response.location == "/"


def test_enabled_quick_sale_does_not_depend_on_pos(monkeypatch):
    checked_features = []

    def feature_enabled(feature):
        checked_features.append(feature)
        return feature == "quick_sale"

    monkeypatch.setattr(
        quick_sale_routes,
        "tenant_feature_enabled",
        feature_enabled,
    )

    with _test_app().test_request_context("/quick-sale/"):
        session["user_id"] = 1
        response = quick_sale_routes.quick_sale_feature_guard()

    assert response is None
    assert checked_features == ["quick_sale"]


def test_disabled_quick_sale_blocks_its_api(monkeypatch):
    monkeypatch.setattr(
        quick_sale_routes,
        "tenant_feature_enabled",
        lambda feature: feature != "quick_sale",
    )

    with _test_app().test_request_context("/quick-sale/products"):
        session["user_id"] = 1
        response, status = quick_sale_routes.quick_sale_feature_guard()

    assert status == 403
    assert response.get_json()["success"] is False
