"""Courier posting from workspace uses ShippingReport and only safe matched rows."""
import sys
import uuid
from pathlib import Path

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
        from models.shipping_report import ShippingReport
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_issue import (
            CourierStatementAnalysisIssue,
        )
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.services.courier_settlement.courier_posting_service import (
            CourierPostingService,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="محمد علي", phone="07701234567")
        db.session.add(customer)
        db.session.flush()

        inv_safe = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=560000,
            paid_amount=0,
        )
        inv_blocked = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=420000,
            paid_amount=0,
        )
        db.session.add_all([inv_safe, inv_blocked])
        db.session.flush()

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        analysis = CourierStatementAnalysis(
            session_id=ws.id,
            document_id="doc-courier-posting",
            tenant_slug=tenant,
            user_id=1,
            status="completed",
            total_rows=2,
            matched_rows=2,
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
        db.session.add_all([row_safe, row_blocked])
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

        preview = CourierPostingService.build_preview(analysis)
        assert preview["safe_rows"] == 1
        assert preview["blocked_rows"] == 1

        posting = CourierPostingService.post_approved(ws, analysis, user_id=1)

        db.session.refresh(inv_safe)
        db.session.refresh(inv_blocked)
        assert inv_safe.payment_status == "مسدد"
        assert inv_safe.status == "تم التوصيل"
        assert inv_safe.paid_amount == inv_safe.total
        assert inv_blocked.payment_status == "غير مسدد"
        assert inv_blocked.status == "تم الطلب"

        report = ShippingReport.query.get(posting["shipping_report_id"])
        assert report is not None
        assert report.is_executed is True
        assert report.orders_count == 1
        assert str(inv_safe.id) in (report.order_status_selections or "")
        assert str(inv_blocked.id) not in (report.order_status_selections or "")

        assert InvoicePaymentLedger.query.filter_by(invoice_id=inv_safe.id).count() == 1
        assert InvoicePaymentLedger.query.filter_by(invoice_id=inv_blocked.id).count() == 0
        assert Expense.query.filter_by(amount=10000).count() == 1
        print("test_posts_only_safe_matched_rows_via_shipping_report ok")


if __name__ == "__main__":
    test_posts_only_safe_matched_rows_via_shipping_report()
    print("courier posting service tests passed")
