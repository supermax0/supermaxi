"""Courier posting from workspace uses ShippingReport and only safe matched rows."""
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _setup():
    from app import app

    tenant = f"test_courier_post_{uuid.uuid4().hex[:8]}"
    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema_for_tenant

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema_for_tenant(tenant)
    return app, tenant


def test_posts_only_safe_matched_rows_via_shipping_report():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.expense import Expense
        from models.invoice import Invoice
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from models.shipping import ShippingCompany
        from models.shipping_payment import ShippingPayment
        from models.shipping_report import ShippingReport
        from models.treasury_account import TreasuryAccount
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_issue import (
            CourierStatementAnalysisIssue,
        )
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingError,
            CourierPostingService,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="محمد علي", phone="07701234567")
        shipping_company = ShippingCompany(
            name="شركة اختبار النقل",
            phone="07709999999",
        )
        master_account = TreasuryAccount(
            name="تحويل ماستر",
            account_type="bank",
            is_active=True,
        )
        db.session.add_all([customer, shipping_company, master_account])
        db.session.flush()

        inv_safe = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=560000,
            paid_amount=0,
            shipping_company_id=shipping_company.id,
        )
        inv_blocked = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=420000,
            paid_amount=0,
        )
        inv_fee_only = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم التوصيل",
            payment_status="مسدد",
            total=169000,
            paid_amount=169000,
            shipping_company_id=shipping_company.id,
        )
        inv_piece = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="جاري الشحن",
            payment_status="جزئي",
            total=314000,
            paid_amount=145000,
            shipping_company_id=shipping_company.id,
            shipping_barcode="508",
            shipping_barcodes_json=json.dumps(["508", "210605"]),
        )
        db.session.add_all([inv_safe, inv_blocked, inv_fee_only, inv_piece])
        db.session.flush()
        old_partial_date = datetime(2026, 7, 27, 11, 40, 34)
        db.session.add(
            InvoicePaymentLedger(
                invoice_id=inv_piece.id,
                amount_delta=145000,
                recorded_at=old_partial_date,
            )
        )

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="courier.pdf",
            stored_filename="courier.pdf",
            storage_path="test/courier.pdf",
            mime_type="application/pdf",
            file_ext=".pdf",
            file_size=1,
            status="preview_ready",
        )
        db.session.add(doc)
        db.session.flush()
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id=doc.id,
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            total_rows=4,
            matched_rows=4,
        )
        db.session.add(analysis)
        db.session.flush()

        row_safe = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=1,
            normalized_order_number=str(inv_safe.id),
            collected_amount=560000,
            delivery_fee=10000,
            matched_invoice_id=inv_safe.id,
            match_score=95,
            match_status="matched",
        )
        row_blocked = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=2,
            normalized_order_number=str(inv_blocked.id),
            collected_amount=390000,
            delivery_fee=8000,
            matched_invoice_id=inv_blocked.id,
            match_score=90,
            match_status="matched",
        )
        row_fee_only = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=3,
            normalized_order_number=str(inv_fee_only.id),
            collected_amount=None,
            delivery_fee=12000,
            net_amount=None,
            matched_invoice_id=inv_fee_only.id,
            match_score=100,
            match_status="matched",
        )
        row_piece = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=4,
            normalized_order_number="210605",
            collected_amount=169000,
            delivery_fee=8000,
            net_amount=161000,
            matched_invoice_id=inv_piece.id,
            match_score=100,
            match_status="matched",
        )
        db.session.add_all([row_safe, row_blocked, row_fee_only, row_piece])
        db.session.flush()

        issue = CourierStatementAnalysisIssue(
            analysis_id=analysis.id,
            row_id=row_blocked.id,
            issue_type="AMOUNT_MISMATCH",
            severity="critical",
            message="مبلغ الطلب الثاني غير مطابق",
        )
        db.session.add(issue)
        db.session.commit()

        payment_choice = CourierPostingService.set_row_payment_method(
            analysis,
            row_safe.id,
            master_account.id,
            user_id=1,
        )
        assert payment_choice["row"]["treasury_account_id"] == master_account.id
        assert payment_choice["payment_method"]["label"] == "تحويل — تحويل ماستر"

        zero_bank_choice = CourierPostingService.set_row_payment_method(
            analysis,
            row_fee_only.id,
            master_account.id,
            user_id=1,
        )
        db.session.refresh(row_fee_only)
        assert zero_bank_choice["zero_collection_confirmed"] is True
        assert row_fee_only.collected_amount == 0
        assert row_fee_only.net_amount == -12000
        assert not CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id,
            row_id=row_fee_only.id,
            issue_type="MISSING_REQUIRED_AMOUNT",
        ).first()

        preview = CourierPostingService.build_preview(analysis)
        assert preview["safe_rows"] == 3
        assert preview["blocked_rows"] == 1
        assert preview["total_collected_amount"] == 729000
        assert preview["delivery_fee_expense_amount"] == 30000

        approved_preview = CourierPostingService.request_approval(
            ws,
            analysis,
            user_id=1,
        )
        assert CourierPostingService.validate_pending_approval(
            ws,
            analysis,
        )["safe_rows"] == approved_preview["safe_rows"]
        CourierPostingService.cancel_approval(ws, analysis, user_id=1)
        with pytest.raises(CourierPostingError, match="تغيّرت حسابات الكشف"):
            CourierPostingService.validate_pending_approval(ws, analysis)
        CourierPostingService.request_approval(ws, analysis, user_id=1)

        posting = CourierPostingService.post_approved(ws, analysis, user_id=1)

        db.session.refresh(inv_safe)
        db.session.refresh(inv_blocked)
        db.session.refresh(inv_fee_only)
        db.session.refresh(inv_piece)
        assert inv_safe.payment_status == "مسدد"
        assert inv_safe.status == "تم التوصيل"
        assert inv_safe.paid_amount == inv_safe.total
        assert inv_blocked.payment_status == "غير مسدد"
        assert inv_blocked.status == "تم الطلب"
        assert inv_fee_only.payment_status == "مسدد"
        assert inv_fee_only.paid_amount == 169000
        assert inv_piece.payment_status == "مسدد"
        assert inv_piece.paid_amount == 314000
        assert inv_piece.status == "تم التوصيل"

        report = ShippingReport.query.get(posting["shipping_report_id"])
        assert report is not None
        assert report.is_executed is True
        assert report.orders_count == 3
        assert str(inv_safe.id) in (report.order_status_selections or "")
        assert str(inv_blocked.id) not in (report.order_status_selections or "")
        assert str(inv_fee_only.id) in (report.order_status_selections or "")
        assert str(inv_piece.id) in (report.order_status_selections or "")

        safe_ledger = InvoicePaymentLedger.query.filter_by(invoice_id=inv_safe.id).one()
        assert safe_ledger.treasury_account_id == master_account.id
        assert InvoicePaymentLedger.query.filter_by(invoice_id=inv_blocked.id).count() == 0
        assert InvoicePaymentLedger.query.filter_by(invoice_id=inv_fee_only.id).count() == 0
        piece_ledger = (
            InvoicePaymentLedger.query.filter_by(invoice_id=inv_piece.id)
            .order_by(InvoicePaymentLedger.recorded_at.asc())
            .all()
        )
        assert [row.amount_delta for row in piece_ledger] == [145000, 169000]

        # The old 145k installment keeps its old date and only 169k belongs to
        # this posting day. The fee-only prepaid order creates no collection.
        piece_shipping_rows = (
            ShippingPayment.query.filter_by(invoice_id=inv_piece.id, action="تسديد")
            .order_by(ShippingPayment.created_at.asc(), ShippingPayment.id.asc())
            .all()
        )
        assert [row.amount for row in piece_shipping_rows] == [145000, 169000]
        assert piece_shipping_rows[0].created_at == old_partial_date
        assert (
            ShippingPayment.query.filter_by(
                invoice_id=inv_fee_only.id,
                action="تسديد",
            ).count()
            == 0
        )
        fee_only_expense = Expense.query.filter_by(amount=12000).one()
        assert fee_only_expense.treasury_account_id == master_account.id
        safe_shipping_payment = ShippingPayment.query.filter_by(
            invoice_id=inv_safe.id,
            action="تسديد",
        ).one()
        assert safe_shipping_payment.treasury_account_id == master_account.id
        report_rows = json.loads(report.orders_data)
        safe_report_row = next(
            item for item in report_rows if item["order_id"] == inv_safe.id
        )
        assert safe_report_row["treasury_account_id"] == master_account.id
        safe_expense = Expense.query.filter_by(amount=10000).one()
        assert safe_expense.treasury_account_id == master_account.id
        assert Expense.query.filter_by(amount=12000).count() == 1
        assert Expense.query.filter_by(amount=8000).count() == 1
        print("test_posts_only_safe_matched_rows_via_shipping_report ok")


def test_global_statement_total_error_blocks_all_rows():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_issue import (
            CourierStatementAnalysisIssue,
        )
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingService,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="اختبار", phone="07700000000")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=100000,
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="global-blocker.pdf",
            stored_filename="global-blocker.pdf",
            storage_path="test/global-blocker.pdf",
            mime_type="application/pdf",
            file_ext=".pdf",
            file_size=1,
            status="preview_ready",
        )
        db.session.add(doc)
        db.session.flush()
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id=doc.id,
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            total_rows=1,
            matched_rows=1,
        )
        db.session.add(analysis)
        db.session.flush()
        row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=1,
            normalized_order_number=str(invoice.id),
            collected_amount=100000,
            delivery_fee=5000,
            net_amount=95000,
            matched_invoice_id=invoice.id,
            match_score=100,
            match_status="matched",
        )
        db.session.add(row)
        db.session.add(
            CourierStatementAnalysisIssue(
                analysis_id=analysis.id,
                row_id=None,
                issue_type="STATEMENT_TOTAL_MISMATCH",
                severity="critical",
                message="المجموع المطبوع لا يطابق الصفوف",
            )
        )
        db.session.commit()

        preview = CourierPostingService.build_preview(analysis)
        assert preview["safe_rows"] == 0
        assert preview["blocked_rows"] == 1
        assert len(preview["global_blockers"]) == 1


def test_zero_courier_collection_confirmed_as_bank_transfer_settles_to_bank():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from models.shipping import ShippingCompany
        from models.shipping_payment import ShippingPayment
        from models.treasury_account import TreasuryAccount
        from modules.workspace.models.courier_statement_analysis import (
            CourierStatementAnalysis,
        )
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingService,
        )
        from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
            InvoiceSnapshotAdapter,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="زبون تحويل", phone="07701112222")
        company = ShippingCompany(name="شركة نقل", phone="07709990000")
        bank = TreasuryAccount(
            name="بطاقة ماستر",
            account_type="bank",
            is_active=True,
        )
        db.session.add_all([customer, company, bank])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="جاري الشحن",
            payment_status="غير مسدد",
            total=349000,
            paid_amount=0,
            shipping_company_id=company.id,
        )
        db.session.add(invoice)
        db.session.flush()
        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="bank-zero.pdf",
            stored_filename="bank-zero.pdf",
            storage_path="test/bank-zero.pdf",
            mime_type="application/pdf",
            file_ext=".pdf",
            file_size=1,
            status="preview_ready",
        )
        db.session.add(doc)
        db.session.flush()
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id=doc.id,
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            courier_company_id=company.id,
            total_rows=1,
            matched_rows=1,
        )
        db.session.add(analysis)
        db.session.flush()
        row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=1,
            normalized_order_number=str(invoice.id),
            collected_amount=None,
            delivery_fee=0,
            net_amount=None,
            matched_invoice_id=invoice.id,
            match_score=100,
            match_status="matched",
        )
        row.set_invoice_snapshot(InvoiceSnapshotAdapter.from_invoice(invoice))
        db.session.add(row)
        db.session.commit()

        choice = CourierPostingService.set_row_payment_method(
            analysis,
            row.id,
            bank.id,
            user_id=1,
            tenant_slug=tenant,
        )
        assert choice["bank_transfer_confirmed"] is True
        # Rows saved by an older deployment may have the bank account without
        # the newer warning marker. The explicit bank selection must still be
        # sufficient to confirm a zero courier collection.
        row.set_warnings([])
        db.session.commit()
        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )

        refreshed = CourierReadonlyAnalysisService.refresh_after_manual_row_change(
            analysis,
            user_id=1,
            tenant_slug=tenant,
        )
        assert not any(
            issue["issue_type"] == "AMOUNT_MISMATCH"
            for issue in refreshed["issues"]
        )
        preview = CourierPostingService.build_preview(analysis)
        assert preview["safe_rows"] == 1
        assert preview["blocked_rows"] == 0
        assert preview["total_collected_amount"] == 349000
        assert preview["statement_collected_amount"] == 0
        assert preview["direct_bank_transfer_amount"] == 349000
        assert preview["payment_accounts"] == [{
            "account_id": bank.id,
            "account_name": "بطاقة ماستر",
            "account_type": "bank",
            "rows_count": 1,
            "settlement_amount": 349000,
            "statement_collection_amount": 0,
            "direct_bank_amount": 349000,
            "reclassified_amount": 0,
            "delivery_fee_amount": 0,
        }]

        CourierPostingService.post_approved(ws, analysis, user_id=1)
        db.session.refresh(invoice)
        assert invoice.payment_status == "مسدد"
        assert invoice.paid_amount == 349000
        ledger = InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).one()
        assert ledger.amount_delta == 349000
        assert ledger.treasury_account_id == bank.id
        shipping_payment = ShippingPayment.query.filter_by(
            invoice_id=invoice.id,
            action="تسديد",
        ).one()
        assert shipping_payment.amount == 349000
        assert shipping_payment.treasury_account_id == bank.id


def test_paid_cash_order_selected_as_master_is_reclassified_out_of_cash():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from models.shipping import ShippingCompany
        from models.shipping_payment import ShippingPayment
        from models.treasury_account import TreasuryAccount
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingService,
        )
        from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
            InvoiceSnapshotAdapter,
        )
        from modules.workspace.services.session_service import SessionService
        from utils.treasury_calculations import calculate_treasury_balance
        from utils.treasury_helpers import get_default_cash_account

        customer = Customer(name="زبون ماستر", phone="07802600400")
        company = ShippingCompany(name="شركة التوصيل", phone="07709990000")
        cash = get_default_cash_account()
        master = TreasuryAccount(
            name="بطاقة ماستر",
            account_type="bank",
            is_active=True,
        )
        db.session.add_all([customer, company, master])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم التوصيل",
            shipping_status="تم التسديد",
            payment_status="مسدد",
            total=365000,
            paid_amount=365000,
            shipping_company_id=company.id,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add_all([
            InvoicePaymentLedger(
                invoice_id=invoice.id,
                amount_delta=365000,
                treasury_account_id=cash.id,
            ),
            ShippingPayment(
                shipping_company_id=company.id,
                invoice_id=invoice.id,
                amount=365000,
                action="تسديد",
                treasury_account_id=cash.id,
            ),
        ])

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="master-reclass.pdf",
            stored_filename="master-reclass.pdf",
            storage_path="test/master-reclass.pdf",
            mime_type="application/pdf",
            file_ext=".pdf",
            file_size=1,
            status="preview_ready",
        )
        db.session.add(doc)
        db.session.flush()
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id=doc.id,
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            courier_company_id=company.id,
            total_rows=1,
            matched_rows=1,
        )
        db.session.add(analysis)
        db.session.flush()
        row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=1,
            normalized_order_number=str(invoice.id),
            collected_amount=0,
            delivery_fee=6000,
            net_amount=-6000,
            matched_invoice_id=invoice.id,
            match_score=100,
            match_status="matched",
            treasury_account_id=master.id,
        )
        row.set_invoice_snapshot(InvoiceSnapshotAdapter.from_invoice(invoice))
        db.session.add(row)
        db.session.commit()

        preview = CourierPostingService.build_preview(analysis)
        assert preview["total_collected_amount"] == 365000
        assert preview["reclassified_payment_amount"] == 365000
        assert preview["payment_accounts"] == [{
            "account_id": master.id,
            "account_name": "بطاقة ماستر",
            "account_type": "bank",
            "rows_count": 1,
            "settlement_amount": 365000,
            "statement_collection_amount": 0,
            "direct_bank_amount": 0,
            "reclassified_amount": 365000,
            "delivery_fee_amount": 6000,
        }]

        posting = CourierPostingService.post_approved(ws, analysis, user_id=1)
        assert posting["result"]["reclassified_payment_count"] == 1
        assert calculate_treasury_balance(cash.id) == 0
        assert calculate_treasury_balance(master.id) == 359000
        allocations = InvoiceSnapshotAdapter.get_payment_allocations(invoice)
        assert [(item["treasury_account_id"], item["amount"]) for item in allocations] == [
            (master.id, 365000)
        ]
        shipping_payment = ShippingPayment.query.filter_by(
            invoice_id=invoice.id,
            action="تسديد",
        ).one()
        assert shipping_payment.treasury_account_id == master.id


def test_execution_applies_replacement_and_small_price_adjustments():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingService,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="اختبار تعديل السعر", phone="07700000001")
        db.session.add(customer)
        db.session.flush()
        replacement = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="جاري الشحن",
            shipping_status="جاري الشحن",
            payment_status="غير مسدد",
            total=195000,
            paid_amount=0,
            shipping_barcode="210618",
            note="",
        )
        small_change = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="جاري الشحن",
            shipping_status="جاري الشحن",
            payment_status="غير مسدد",
            total=289000,
            paid_amount=0,
            shipping_barcode="210621",
        )
        db.session.add_all([replacement, small_change])
        db.session.flush()

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="price-adjustment.pdf",
            stored_filename="price-adjustment.pdf",
            storage_path="test/price-adjustment.pdf",
            mime_type="application/pdf",
            file_ext=".pdf",
            file_size=1,
            status="preview_ready",
        )
        db.session.add(doc)
        db.session.flush()
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id=doc.id,
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            total_rows=2,
            matched_rows=2,
        )
        db.session.add(analysis)
        db.session.flush()
        replacement_row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=1,
            normalized_order_number="210618",
            collected_amount=185000,
            delivery_fee=6000,
            net_amount=179000,
            matched_invoice_id=replacement.id,
            match_score=80,
            match_status="matched",
        )
        small_change_row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=2,
            normalized_order_number="210621",
            collected_amount=285000,
            delivery_fee=15000,
            net_amount=270000,
            matched_invoice_id=small_change.id,
            match_score=80,
            match_status="matched",
        )
        db.session.add_all([replacement_row, small_change_row])
        db.session.commit()

        confirmed = CourierPostingService.confirm_row_replacement(
            analysis,
            replacement_row.id,
            user_id=1,
            tenant_slug=tenant,
        )
        assert confirmed["replacement_plan"]["original_total"] == 195000
        assert confirmed["replacement_plan"]["target_total"] == 185000

        preview = CourierPostingService.build_preview(analysis)
        assert preview["safe_rows"] == 2
        posting = CourierPostingService.post_approved(ws, analysis, user_id=1)

        db.session.refresh(replacement)
        db.session.refresh(small_change)
        assert replacement.total == 185000
        assert replacement.status == "استبدال"
        assert replacement.shipping_status == "استبدال"
        assert replacement.payment_status == "مسدد"
        assert "تغير السعر من 195,000 إلى 185,000" in replacement.note
        assert small_change.total == 285000
        assert small_change.status == "تم التوصيل"
        assert small_change.payment_status == "مسدد"
        assert "تغير السعر من 289,000 إلى 285,000" in small_change.note
        assert len(posting["price_adjustments"]) == 2
        assert posting["result"]["replacement_count"] == 1


if __name__ == "__main__":
    test_posts_only_safe_matched_rows_via_shipping_report()
    test_global_statement_total_error_blocks_all_rows()
    test_execution_applies_replacement_and_small_price_adjustments()
    print("courier posting service tests passed")
