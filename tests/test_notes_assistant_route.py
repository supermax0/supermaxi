from flask import Flask

from routes.notes import organize


def test_notes_assistant_endpoint_returns_organized_content():
    app = Flask(__name__)
    with app.test_request_context(
        "/notes/api/organize",
        method="POST",
        json={
            "mode": "tasks",
            "content": "<p>مراجعة المبيعات</p><p>إرسال التقرير</p>",
        },
    ):
        response = organize.__wrapped__()

    payload = response.get_json()
    assert payload["success"] is True
    assert "قائمة المهام" in payload["content"]
    assert "مراجعة المبيعات" in payload["content"]
