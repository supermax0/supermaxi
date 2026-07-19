from unittest.mock import patch

from flask import Flask, g

from modules.mobile_app.services import shared_cache


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key] = value


def test_shared_json_cache_is_tenant_scoped() -> None:
    app = Flask(__name__)
    fake = _FakeRedis()
    with patch.object(shared_cache, "_redis_client", return_value=fake):
        with app.test_request_context("/"):
            g.tenant = "tenant-a"
            shared_cache.set_json("catalog", {"page": 1}, {"items": [1]}, ttl=30)
            assert shared_cache.get_json("catalog", {"page": 1}) == {"items": [1]}

        with app.test_request_context("/"):
            g.tenant = "tenant-b"
            assert shared_cache.get_json("catalog", {"page": 1}) is None
