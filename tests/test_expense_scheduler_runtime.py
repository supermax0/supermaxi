"""Scheduled expenses run under Gunicorn without duplicating withdrawals."""
from datetime import datetime, time, date
import sys
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Production Gunicorn lock uses Linux flock")
def test_competing_workers_skip_the_run_then_acquire_the_released_lock(tmp_path, monkeypatch):
    from routes import expenses
    entered, release = threading.Event(), threading.Event()
    hits, errors = [], []

    def work(app):
        hits.append(1)
        if len(hits) == 1:
            entered.set()
            assert release.wait(10)

    monkeypatch.setattr(expenses, "_post_scheduled_expenses_for_tenants", work)
    app = SimpleNamespace(instance_path=str(tmp_path))

    def first():
        try:
            expenses.run_scheduled_expense_posting_for_all_tenants(app)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert entered.wait(10)
        expenses.run_scheduled_expense_posting_for_all_tenants(app)
        assert len(hits) == 1
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive() and not errors
    expenses.run_scheduled_expense_posting_for_all_tenants(app)
    assert len(hits) == 2


@pytest.mark.parametrize("command, expected", [("/venv/bin/gunicorn", True), ("acceptance.py", False)])
def test_only_real_workers_start_the_financial_timer(monkeypatch, command, expected):
    import app as entry
    import apscheduler.schedulers.background as background
    started = []

    class Scheduler:
        def add_job(self, fn, trigger, **kwargs):
            assert kwargs["max_instances"] == 1
            assert kwargs["coalesce"] is True

        def start(self):
            started.append(True)

    monkeypatch.setattr(background, "BackgroundScheduler", Scheduler)
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    monkeypatch.setenv("SERVER_SOFTWARE", "gunicorn/test")
    monkeypatch.setattr(sys, "argv", [command])
    entry._start_expense_posting_scheduler()
    assert bool(started) is expected


def test_default_local_clock_posts_a_due_expense_once(monkeypatch):
    from tests.test_expense_posting_accounting import _fresh_tenant_db, TENANT
    _fresh_tenant_db()
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.expense import Expense
    from models.account_transaction import AccountTransaction
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    from routes import expenses

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        cash = get_default_cash_account()
        db.session.add(AccountTransaction(type="deposit", amount=500000, note="open", treasury_account_id=cash.id))
        db.session.add(Expense(title="Scheduled", amount=100000, expense_date=date(2026, 10, 20),
                               post_time=time(22), treasury_account_id=cash.id, cash_posted=False))
        db.session.commit()
        monkeypatch.setattr(expenses, "business_now", lambda: datetime(2026, 10, 20, 21, 59))
        assert expenses.post_due_unposted_expenses() == (0, 0)
        monkeypatch.setattr(expenses, "business_now", lambda: datetime(2026, 10, 20, 22))
        assert expenses.post_due_unposted_expenses() == (1, 0)
        assert expenses.post_due_unposted_expenses() == (0, 0)
        assert AccountTransaction.query.filter_by(type="withdraw").count() == 1
        assert calculate_treasury_balance(cash.id) == 400000
