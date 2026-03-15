from types import SimpleNamespace

from modules.publisher.api import posts_api


class _DummyCol:
    def in_(self, _values):
        return None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


def test_validate_post_payload_requires_page_selection(monkeypatch):
    fake_page_model = SimpleNamespace(page_id=_DummyCol(), query=_FakeQuery([]))
    fake_media_model = SimpleNamespace(id=_DummyCol(), query=_FakeQuery([]))
    monkeypatch.setattr(posts_api, "PublisherPage", fake_page_model)
    monkeypatch.setattr(posts_api, "PublisherMedia", fake_media_model)

    _, _, _, _, fields = posts_api._validate_post_payload(
        {"text": "hello", "page_ids": [], "media_ids": []},
        tenant="tenant-a",
    )
    assert fields is not None
    assert "page_ids" in fields


def test_validate_post_payload_rejects_foreign_media(monkeypatch):
    fake_page_model = SimpleNamespace(
        page_id=_DummyCol(),
        query=_FakeQuery([SimpleNamespace(page_id="123")]),
    )
    fake_media_model = SimpleNamespace(
        id=_DummyCol(),
        query=_FakeQuery([SimpleNamespace(id=1)]),
    )
    monkeypatch.setattr(posts_api, "PublisherPage", fake_page_model)
    monkeypatch.setattr(posts_api, "PublisherMedia", fake_media_model)

    _, _, _, _, fields = posts_api._validate_post_payload(
        {"text": "", "page_ids": ["123"], "media_ids": [1, 2]},
        tenant="tenant-a",
    )
    assert fields is not None
    assert "media_ids" in fields
