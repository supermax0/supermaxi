"""«المركز المالي وأين ذهبت الأرباح»: equity = assets − liabilities, and the profit → cash bridge always closes on
the treasury's own change in cash (an identity, nothing estimated)."""
from __future__ import annotations

from datetime import datetime, timedelta

from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

import pytest

URL = "/reports/api/v2/section/equity?period=this_year"


@pytest.fixture()
def ctx(app):  # noqa: F811
    return _make_ctx(app)


def test_equity_and_where_the_profit_went(ctx):
    from flask import g

    from extensions import db
    from models.account_transaction import AccountTransaction

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        db.session.add(AccountTransaction(branch_id=ctx["main"], type="withdraw", amount=300_000, note="سحب مالك شخصي",
                                          treasury_account_id=ctx["cash_id"], created_at=datetime.utcnow() - timedelta(days=1)))
        db.session.commit()
    d = _json(_client(ctx).get(URL))
    pos = d["position"]
    assert pos["balanced"] and pos["equity"] == pos["total_assets"] - pos["total_liabilities"]
    assert pos["total_assets"] == sum(a["amount"] for a in pos["assets"])
    bridge = {b["key"]: b["amount"] for b in d["bridge"]}
    assert bridge["owner"] == -300_000 and bridge["capital"] == 2_000_000  # the «رأس مال» deposit of the fixture
    # the lines explain the whole change in cash, to the dinar
    assert d["profit"]["net_profit"] + sum(bridge.values()) == d["cash"]["net_change"]
    assert d["cash"]["closing"] - d["cash"]["opening"] == d["cash"]["net_change"]
    assert any("سحبه المالك" in s for s in d["summary"]) and d["summary"][0].startswith(("ربحت", "خسرت"))


def test_equity_needs_financial_permission_and_exports(ctx):
    assert _client(ctx, "clerk").get(URL).status_code == 403
    res = _client(ctx).get("/reports/api/v2/export/equity.xlsx?period=this_year")
    assert res.status_code == 200 and res.data[:2] == b"PK"  # a real .xlsx
