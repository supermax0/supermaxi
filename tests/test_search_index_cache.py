"""Sprint 10 scale: the search index is rebuilt by one request at a time; the others are served the previous one,
and identical searches are answered from the per-index result cache."""
from __future__ import annotations

import threading
import time

from modules.search import engine


def _doc(i, category="شاشات"):
    return engine.Doc(id=i, name=f"شاشة {i}", codes=frozenset(), category=category, brand=None, price=100 + i,
                      in_stock=True, quality=0.0, attrs=engine.Attrs(None, None, None, frozenset()),
                      name_norm=f" شاشه {i} ", words=frozenset({"شاشه", str(i)}), cats=frozenset({category}))


def test_an_expired_index_is_rebuilt_once_while_others_get_the_previous_one(monkeypatch):
    engine.invalidate("t-cache")
    builds = []
    gate = threading.Event()

    def slow_build(slug):
        builds.append(slug)
        if len(builds) > 1:
            gate.wait(5)  # the second build (the refresh) is slow
        return [_doc(len(builds))]

    monkeypatch.setattr(engine, "_build", slow_build)
    first = engine.documents("t-cache")
    assert [d.id for d in first] == [1]
    key = "t-cache"
    engine._cache[key] = (time.monotonic() - 1, engine._cache[key][1])  # expire it
    results = []
    refresher = threading.Thread(target=lambda: results.append(engine.documents("t-cache")))
    refresher.start()
    time.sleep(0.2)
    # while the refresh is running, other requests do not wait and do not start another build
    others = [engine.documents("t-cache") for _ in range(5)]
    assert all([d.id for d in o] == [1] for o in others) and len(builds) == 2
    gate.set()
    refresher.join(5)
    assert [d.id for d in results[0]] == [2] and [d.id for d in engine.documents("t-cache")] == [2]
    engine.invalidate("t-cache")


def test_same_search_is_served_from_the_result_cache(monkeypatch):
    engine.invalidate("t-results")
    monkeypatch.setattr(engine, "_build", lambda slug: [_doc(1), _doc(2), _doc(3, "غسالات")])
    calls = []
    real = engine._search

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "_search", counting)
    a = engine.search("t-results", "شاشة")
    b = engine.search("t-results", "شاشة")
    assert a is b and len(calls) == 1 and set(a.ids) == {1, 2}
    engine.search("t-results", "شاشة", province="بغداد")  # a different key
    assert len(calls) == 2
    engine.invalidate("t-results")
    engine.search("t-results", "شاشة")  # a rebuilt index starts with an empty cache
    assert len(calls) == 3
    engine.invalidate("t-results")
