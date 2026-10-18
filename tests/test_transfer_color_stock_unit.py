"""Regression: transfer receive must credit the destination color row."""

from types import SimpleNamespace


class _Col:
    def in_(self, *_a, **_k):
        return self

    def desc(self):
        return self

    def __eq__(self, other):
        return self

    def __add__(self, other):
        return self

    def __hash__(self):
        return id(self)


def test_ensure_color_variant_returns_requested_product_not_sibling(monkeypatch):
    """Shared-catalog siblings with higher qty must not be reused."""
    import utils.product_color_service as colors

    dest_variant = SimpleNamespace(
        id=2,
        product_id=20,
        color_name="ابيض",
        quantity=0,
        buy_price=100,
        sale_price=200,
        governorate_sale_price=None,
    )
    lookups = []

    class FakeQuery:
        def filter_by(self, **kwargs):
            lookups.append(("filter_by", kwargs))
            if int(kwargs.get("product_id") or 0) == 20 and kwargs.get("color_name") == "ابيض":
                self._row = dest_variant
            else:
                self._row = None
            return self

        def filter(self, *args, **kwargs):
            lookups.append(("filter", args, kwargs))
            self._row = None
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return getattr(self, "_row", None)

    class FakeSession:
        def add(self, obj):
            raise AssertionError(f"should reuse destination row, got {obj}")

        def flush(self):
            return None

    monkeypatch.setattr(
        colors,
        "Product",
        SimpleNamespace(
            query=SimpleNamespace(
                get=lambda _id: SimpleNamespace(
                    id=20,
                    buy_price=100,
                    sale_price=200,
                    governorate_sale_price=None,
                    meta_json='{"has_colors": true}',
                )
            )
        ),
    )
    monkeypatch.setattr(colors, "ProductColorVariant", SimpleNamespace(query=FakeQuery()))
    monkeypatch.setattr(colors.db, "session", FakeSession())
    monkeypatch.setattr(colors, "_set_has_colors_flag", lambda *_a, **_k: None)
    monkeypatch.setattr(colors, "_shared_catalog_product_ids", lambda _pid: [10, 20])

    ensured = colors.ensure_color_variant(20, "ابيض")
    assert int(ensured.product_id) == 20
    assert lookups and lookups[0][0] == "filter_by"


def test_ensure_color_variant_creates_local_when_only_sibling_exists(monkeypatch):
    import utils.product_color_service as colors

    created = []
    source_variant = SimpleNamespace(
        id=1,
        product_id=10,
        color_name="ابيض",
        quantity=4,
        buy_price=80,
        sale_price=180,
        governorate_sale_price=None,
    )

    class FakeQuery:
        def filter_by(self, **kwargs):
            self._mode = "by"
            return self

        def filter(self, *args, **kwargs):
            self._mode = "shared"
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            if getattr(self, "_mode", None) == "by":
                return None
            return source_variant

    class FakeSession:
        def add(self, obj):
            created.append(obj)
            obj.id = 99

        def flush(self):
            return None

    class FakeVariantModel:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        query = FakeQuery()
        product_id = _Col()
        color_name = _Col()
        quantity = _Col()

    monkeypatch.setattr(
        colors,
        "Product",
        SimpleNamespace(
            query=SimpleNamespace(
                get=lambda _id: SimpleNamespace(
                    id=20,
                    buy_price=100,
                    sale_price=200,
                    governorate_sale_price=None,
                    meta_json=None,
                )
            )
        ),
    )
    monkeypatch.setattr(colors, "ProductColorVariant", FakeVariantModel)
    monkeypatch.setattr(colors.db, "session", FakeSession())
    monkeypatch.setattr(colors, "_shared_catalog_product_ids", lambda _pid: [10, 20])
    monkeypatch.setattr(colors, "_set_has_colors_flag", lambda *_a, **_k: None)

    result = colors.ensure_color_variant(20, "ابيض", initial_qty=0)
    assert created
    assert int(created[0].product_id) == 20
    assert created[0].color_name == "ابيض"
    assert int(created[0].buy_price) == 80  # copied from sibling
    assert int(result.product_id) == 20


def test_receive_color_stock_updates_ensured_local_row(monkeypatch):
    import utils.product_color_service as colors

    dest = SimpleNamespace(id=2, product_id=20, color_name="ابيض", quantity=0)
    updates = []

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def update(self, values, synchronize_session=False):
            updates.append(True)
            return 1

    class FakeSession:
        def query(self, *_args):
            return FakeQuery()

        def expire(self, _obj):
            return None

        def flush(self):
            return None

    monkeypatch.setattr(colors, "ensure_color_variant", lambda pid, color, initial_qty=0: dest)
    monkeypatch.setattr(colors.db, "session", FakeSession())
    monkeypatch.setattr(
        colors,
        "ProductColorVariant",
        SimpleNamespace(id=_Col(), quantity=_Col()),
    )
    synced = []
    monkeypatch.setattr(colors, "sync_product_total_from_colors", lambda pid: synced.append(pid) or 0)

    result = colors.receive_color_stock(20, "ابيض", 2)
    assert result is dest
    assert updates
    assert synced == [20]
