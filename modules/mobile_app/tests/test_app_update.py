"""Unit tests for Social in-app update metadata."""
from __future__ import annotations

import json

from flask import Flask


def test_get_app_update_payload_defaults_and_version_json(tmp_path, monkeypatch):
    from modules.mobile_app.services import app_update as svc

    downloads = tmp_path / "static" / "downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(svc, "_downloads_dir", lambda: downloads)

    for key in (
        "APP_SOCIAL_APK_VERSION",
        "APP_SOCIAL_APK_BUILD",
        "APP_SOCIAL_APK_MIN_VERSION",
        "APP_SOCIAL_APK_MIN_BUILD",
        "APP_SOCIAL_APK_URL",
        "APP_SOCIAL_APK_FORCE",
        "APP_SOCIAL_APK_UPDATE_MESSAGE",
    ):
        monkeypatch.delenv(key, raising=False)

    app = Flask(__name__)
    with app.test_request_context("/"):
        payload = svc.get_app_update_payload()
    assert payload["latest_version"] == "1.2.0"
    assert payload["latest_build"] == 3
    assert payload["min_version"] == "1.0.0"
    assert payload["min_build"] == 1
    assert payload["apk_url"].endswith("/static/downloads/finora-social.apk")
    assert payload["force"] is False
    assert "Finora" in payload["message"]

    (downloads / "finora-social-version.json").write_text(
        json.dumps(
            {
                "latest_version": "1.3.0",
                "latest_build": 9,
                "min_version": "1.2.0",
                "min_build": 3,
                "apk_url": "/static/downloads/finora-social.apk",
                "force": True,
                "message": "تحديث إجباري للتجربة",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_SOCIAL_APK_VERSION", "9.9.9")
    monkeypatch.setenv("APP_SOCIAL_APK_BUILD", "99")

    with app.test_request_context("/"):
        payload = svc.get_app_update_payload()
    assert payload["latest_version"] == "1.3.0"
    assert payload["latest_build"] == 9
    assert payload["min_version"] == "1.2.0"
    assert payload["min_build"] == 3
    assert payload["force"] is True
    assert payload["message"] == "تحديث إجباري للتجربة"
