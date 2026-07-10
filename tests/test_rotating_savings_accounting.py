"""
اختبارات قبول الجمعيات والسلف الدوّارة — Tests 1-5 من المواصفات.
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from models.rotating_savings import RotatingSaving, RotatingSavingPayment
from utils.accounting_logic import ACCOUNT_CODES, initialize_accounts
from utils.rotating_savings_schema_guard import ensure_rotating_savings_schema
from utils.rotating_savings_service import (
    build_saving_from_form,
    ensure_rotating_savings_gl_accounts,
    record_payment,
    record_receipt,
    record_fee,
    recalculate_balances,
    RS_GL,
)


class RotatingSavingsAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app

        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        db.create_all()
        initialize_accounts()
        ensure_rotating_savings_schema()
        ensure_rotating_savings_gl_accounts()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.ctx.pop()

    def _cash_balance(self):
        cash = Account.query.filter_by(code=ACCOUNT_CODES["CASH"]).first()
        if not cash:
            return 0
        debits = (
            db.session.query(db.func.coalesce(db.func.sum(JournalEntry.amount), 0))
            .filter(JournalEntry.debit_account_id == cash.id)
            .scalar()
        )
        credits = (
            db.session.query(db.func.coalesce(db.func.sum(JournalEntry.amount), 0))
            .filter(JournalEntry.credit_account_id == cash.id)
            .scalar()
        )
        return int(debits or 0) - int(credits or 0)

    def _expense_total(self):
        exp = Account.query.filter_by(code=RS_GL["FEE_EXPENSE"]).first()
        if not exp:
            return 0
        debits = (
            db.session.query(db.func.coalesce(db.func.sum(JournalEntry.amount), 0))
            .filter(JournalEntry.debit_account_id == exp.id)
            .scalar()
        )
        return int(debits or 0)

    def test_1_company_payment_before_receive(self):
        """Test 1: Cash decreases, asset increases, no P&L effect."""
        cash_before = self._cash_balance()
        saving = build_saving_from_form({
            "name": "جمعية اختبار 1",
            "type": "company",
            "monthly_amount": "1000000",
            "total_months": "10",
            "start_date": date.today().isoformat(),
        })
        db.session.commit()
        record_payment(saving, date.today(), 1_000_000, user_id=1)
        db.session.commit()
        recalculate_balances(saving)
        self.assertEqual(saving.total_paid, 1_000_000)
        self.assertEqual(saving.asset_balance, 1_000_000)
        self.assertEqual(saving.liability_balance, 0)
        cash_after = self._cash_balance()
        self.assertEqual(cash_before - cash_after, 1_000_000)
        fee_exp = self._expense_total()
        self.assertEqual(fee_exp, 0)

    def test_2_receive_more_than_paid(self):
        """Test 2: Receive 12M after paying 10M → liability 2M."""
        cash_before = self._cash_balance()
        saving = build_saving_from_form({
            "name": "جمعية اختبار 2",
            "type": "company",
            "monthly_amount": "1000000",
            "total_months": "12",
            "expected_receive_amount": "12000000",
            "start_date": date.today().isoformat(),
            "prior_payments_count": "10",
            "prior_payment_amount": "1000000",
            "prior_combined_entry": "1",
        })
        db.session.commit()
        # الدفعات السابقة رصيد افتتاحي — لا تخصم من الصندوق/النقدية
        self.assertEqual(self._cash_balance(), cash_before)
        self.assertEqual(saving.total_paid, 10_000_000)
        self.assertTrue(
            all(p.treasury_transaction_id is None for p in saving.payments),
            "prior payments must not withdraw from treasury",
        )
        record_receipt(saving, date.today(), 12_000_000, user_id=1)
        db.session.commit()
        recalculate_balances(saving)
        self.assertEqual(saving.total_paid, 10_000_000)
        self.assertEqual(saving.total_received, 12_000_000)
        self.assertEqual(saving.liability_balance, 2_000_000)
        self.assertEqual(saving.asset_balance, 0)

    def test_4_owner_personal(self):
        """Test 4: Owner drawings, no asset, no expense."""
        saving = build_saving_from_form({
            "name": "جمعية شخصية",
            "type": "owner_personal",
            "monthly_amount": "1000000",
            "total_months": "10",
            "start_date": date.today().isoformat(),
        })
        db.session.commit()
        record_payment(saving, date.today(), 1_000_000, user_id=1)
        db.session.commit()
        self.assertEqual(saving.asset_balance, 0)
        self.assertEqual(saving.owner_drawings_balance, 1_000_000)
        self.assertEqual(self._expense_total(), 0)

    def test_5_fee_only_in_expense(self):
        """Test 5: Only fee hits expense account."""
        saving = build_saving_from_form({
            "name": "جمعية رسوم",
            "type": "company",
            "monthly_amount": "1000000",
            "total_months": "10",
            "start_date": date.today().isoformat(),
        })
        db.session.commit()
        record_fee(saving, date.today(), 50_000, user_id=1)
        db.session.commit()
        self.assertEqual(self._expense_total(), 50_000)


if __name__ == "__main__":
    unittest.main()
