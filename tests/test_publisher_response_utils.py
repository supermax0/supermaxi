from flask import Flask

from modules.publisher.api.response_utils import error_response, ok_response


def test_ok_response_shape():
    app = Flask(__name__)
    with app.app_context():
        response, status_code = ok_response(
            data={"items": [1, 2]},
            message="done",
            meta={"page": 1},
            legacy={"posts": [1, 2]},
        )
    payload = response.get_json()
    assert status_code == 200
    assert payload["success"] is True
    assert payload["data"]["items"] == [1, 2]
    assert payload["meta"]["page"] == 1
    assert payload["posts"] == [1, 2]


def test_error_response_shape():
    app = Flask(__name__)
    with app.app_context():
        response, status_code = error_response(
            code="validation_error",
            message="invalid",
            status_code=422,
            fields={"page_ids": "required"},
        )
    payload = response.get_json()
    assert status_code == 422
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["fields"]["page_ids"] == "required"
