"""Manual courier-row order correction keeps the analysis internally consistent."""
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _setup():
    from app import app

    tenant = f"test_courier_correct_{uuid.uuid4().hex[:8]}"
    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema_for_tenant

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema_for_tenant(tenant)
    return app, tenant


def test_correct_row_order_rebuilds_analysis_and_rejects_missing_order():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.workspace.models.courier_statement_analysis import (
            CourierStatementAnalysis,
        )
        from modules.workspace.models.courier_statement_analysis_issue import (
            CourierStatementAnalysisIssue,
        )
        from modules.workspace.models.courier_statement_analysis_row import (
            CourierStatementAnalysisRow,
        )
        from modules.workspace.models.workspace_document import WorkspaceDocument
        from modules.workspace.services.courier_settlement.courier_analysis_errors import (
            CourierAnalysisNotFoundError,
        )
        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )
        from modules.workspace.services.session_service import SessionService

        customer = Customer(name="أم محمد", phone="07701234567")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            status="تم الطلب",
            payment_status="غير مسدد",
            total=145000,
            paid_amount=0,
            barcode="210771",
        )
        db.session.add(invoice)
        db.session.flush()

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        doc = WorkspaceDocument(
            session_id=ws.id,
            tenant_slug=tenant,
            user_id=1,
            original_filename="courier.png",
            stored_filename="courier.png",
            storage_path="test/courier.png",
            mime_type="image/png",
            file_ext=".png",
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
            unmatched_rows=1,
        )
        analysis.set_summary({"statement_totals": {}, "extraction": {}})
        db.session.add(analysis)
        db.session.flush()
        row = CourierStatementAnalysisRow(
            analysis_id=analysis.id,
            row_index=12,
            raw_order_number="2100777",
            normalized_order_number="2100777",
            customer_name=customer.name,
            customer_phone=customer.phone,
            collected_amount=145000,
            delivery_fee=8000,
            net_amount=137000,
            match_score=0,
            match_status="unmatched",
        )
        db.session.add(row)
        db.session.flush()
        db.session.add(
            CourierStatementAnalysisIssue(
                analysis_id=analysis.id,
                row_id=row.id,
                issue_type="ORDER_NOT_FOUND",
                severity="error",
                message="الطلب غير موجود",
            )
        )
        db.session.commit()

        result = CourierReadonlyAnalysisService.correct_row_order(
            analysis,
            row.id,
            "٢١٠٧٧١",
            user_id=1,
            tenant_slug=tenant,
        )

        db.session.refresh(row)
        db.session.refresh(analysis)
        assert row.normalized_order_number == "210771"
        assert row.matched_invoice_id == invoice.id
        assert row.match_status == "matched"
        assert "manual_order_override" in row.get_match_reasons()
        assert result["row"]["match_explanation"]["manually_corrected"] is True
        assert analysis.matched_rows == 1
        assert analysis.unmatched_rows == 0
        assert not CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id,
            issue_type="ORDER_NOT_FOUND",
        ).first()

        row.customer_phone = "07799999999"
        row.match_status = "review"
        row.match_score = 50
        row.matched_invoice_id = invoice.id
        row.set_match_reasons([
            "order_number_exact",
            "phone_mismatch_hint",
            "amount_matches",
        ])
        row.set_invoice_snapshot({"id": invoice.id, "order_number": "210771"})
        analysis.matched_rows = 0
        analysis.review_rows = 1
        db.session.commit()

        approved = CourierReadonlyAnalysisService.approve_row_candidate(
            analysis,
            row.id,
            user_id=1,
            tenant_slug=tenant,
        )

        db.session.refresh(row)
        db.session.refresh(analysis)
        assert row.match_status == "matched"
        assert row.match_score >= 75
        assert "manual_candidate_approval" in row.get_match_reasons()
        assert approved["row"]["match_explanation"]["manually_approved"] is True
        assert approved["counts"]["matched"] == 1
        assert approved["counts"]["review"] == 0

        invoice.shipping_barcode = "210771"
        invoice.shipping_barcodes_json = json.dumps(["210771", "210605"])
        db.session.commit()
        found_by_second_barcode = (
            CourierReadonlyAnalysisService._find_invoice_by_order_number(
                "210605",
                "210605",
            )
        )
        assert found_by_second_barcode.id == invoice.id

        with pytest.raises(CourierAnalysisNotFoundError):
            CourierReadonlyAnalysisService.correct_row_order(
                analysis,
                row.id,
                "99999999",
                user_id=1,
                tenant_slug=tenant,
            )
