from flask import Flask


def test_delete_courier_row_route_is_registered():
    from modules.workspace.api.courier_analysis_api import courier_analysis_api_bp

    app = Flask(__name__)
    app.register_blueprint(courier_analysis_api_bp, url_prefix="/workspace/api")
    matching = [
        rule
        for rule in app.url_map.iter_rules()
        if str(rule.rule)
        == "/workspace/api/courier-analysis/<analysis_id>/rows/<row_id>"
    ]
    assert len(matching) == 1
    assert "DELETE" in matching[0].methods
