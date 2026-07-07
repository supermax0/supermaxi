"""Courier readonly analysis service tests — Phase 5."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _pdf_bytes():
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class _FakeFile:
    def __init__(self, filename, data, mimetype=None):
        self.filename = filename
        self.stream = io.BytesIO(data)
        self.mimetype = mimetype

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.stream.getvalue())


def _setup(tenant="test_courier_ro"):
    from app import app

    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
    return app, tenant


def _mock_intel():
    text = "كشف تسديد شركة التوصيل المبلغ المحصل أجور التوصيل الصافي COD"
    return {
        "status": "completed",
        "text": text,
        "text_sample": text,
        "pages": [{"page": 1, "text": text, "method": "pdf_text"}],
        "warnings": [],
    }


def _mock_invoices():
    inv = SimpleNamespace(
        id=10248,
        customer_name="محمد علي",
        customer=SimpleNamespace(phone="07701234567"),
        total=560000,
        status="تم التسليم",
        payment_status="غير مسدد",
        shipping_company_id=1,
        barcode=None,
        shipping_barcode=None,
        created_at=None,
    )
    return [inv]


def test_readonly_analysis_creates_records():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
        from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent
        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.session_service import SessionService

        ws = SessionService.create_session(user_id=40, tenant_slug=tenant)
        doc = DocumentStorageService.upload_to_session(
            ws, _FakeFile("courier.pdf", _pdf_bytes(), "application/pdf"), 40
        )

        tables = {
            "status": "completed",
            "tables": [{
                "page": 1,
                "index": 0,
                "rows": [["#10248", "محمد علي", "560,000", "10,000"]],
                "headers": [],
            }],
        }

        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_intel(),
        ), patch(
            "modules.workspace.services.document_intelligence.document_table_extraction_service."
            "DocumentTableExtractionService.extract_tables",
            return_value=tables,
        ), patch(
            "modules.workspace.services.courier_settlement.courier_order_matcher.CourierOrderMatcher._default_query",
            return_value=_mock_invoices(),
        ), patch(
            "modules.workspace.services.courier_settlement.courier_statement_parser.CourierStatementParser.parse",
            return_value={
                "rows": [{
                    "row_index": 1,
                    "source_table_index": 0,
                    "source_page": 1,
                    "raw_row": ["#10248", "محمد علي", "560,000", "10,000"],
                    "raw_order_number": "#10248",
                    "normalized_order_number": "10248",
                    "customer_name": "محمد علي",
                    "collected_amount": 560000,
                    "delivery_fee": 10000,
                    "net_amount": 550000,
                    "warnings": [],
                }],
                "warnings": [],
            },
        ):
            analysis = CourierReadonlyAnalysisService.analyze(ws.id, doc.id, 40, tenant)

        assert analysis.id
        assert CourierStatementAnalysis.query.get(analysis.id)
        assert CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis.id).count() >= 1

        types = {e.event_type for e in WorkspaceAuditEvent.query.filter_by(session_id=ws.id).all()}
        for ev in (
            "courier.analysis.started",
            "courier.rows.parsed",
            "courier.issues.detected",
            "courier.financial_preview.ready",
            "courier.analysis.completed",
        ):
            assert ev in types
        print("test_readonly_analysis_creates_records ok")


def test_completed_empty_extraction_is_not_readable():
    from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
        CourierReadonlyAnalysisService,
    )

    empty = SimpleNamespace(extracted_text="", get_tables=lambda: [])
    with_text = SimpleNamespace(extracted_text="كشف تسديد", get_tables=lambda: [])
    with_tables = SimpleNamespace(extracted_text="", get_tables=lambda: [{"rows": [["#1"]]}])

    assert not CourierReadonlyAnalysisService._has_readable_extraction(empty)
    assert CourierReadonlyAnalysisService._has_readable_extraction(with_text)
    assert CourierReadonlyAnalysisService._has_readable_extraction(with_tables)
    print("test_completed_empty_extraction_is_not_readable ok")


if __name__ == "__main__":
    test_readonly_analysis_creates_records()
    test_completed_empty_extraction_is_not_readable()
    print("All readonly analysis tests passed.")
