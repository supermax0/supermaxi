"""Sprint 0 baseline: what the storefront costs today as the catalog grows (printed, with loose sanity asserts)."""
from __future__ import annotations

import os

import pytest

from tests.storefront_harness import seed_products, timed_get
from tests.test_branch_management_api import _make_ctx, app  # noqa: F401

SIZES = [int(x) for x in os.environ.get("STOREFRONT_BASELINE_SIZES", "100,1000").split(",")]


@pytest.mark.skipif(not os.environ.get("STOREFRONT_BASELINE"), reason="measurement only")
def test_baseline(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    ids = _make_ctx(app)
    tenant = ids["tenant"]
    client = app.test_client()
    rows = []
    done = 0
    for size in SIZES:
        seed_products(app, tenant, size - done, prefix=f"B{size}")
        done = size
        for label, url in [("home", f"/shop/{tenant}/"), ("home p2", f"/shop/{tenant}/?page=2"),
                           ("search", f"/shop/{tenant}/?q=LG"), ("cart", f"/shop/{tenant}/cart")]:
            r = timed_get(client, url)
            rows.append(f"BASELINE products={size:>6} {label:<8} status={r['status']} html={r['bytes']:>9}B "
                        f"time={r['ms']:>6}ms queries={r['queries']}")
    print("\n" + "\n".join(rows))
