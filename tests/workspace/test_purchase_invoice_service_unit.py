from types import SimpleNamespace


def test_purchase_product_matching_prioritizes_barcode_and_sku():
    from modules.workspace.services.purchase_invoice_service import PurchaseInvoiceService

    products = [
        SimpleNamespace(id=1, name="سيروم ماكس 95", sku="SM-95", barcode="100200", buy_price=12000),
        SimpleNamespace(id=2, name="سيروم قريب", sku="OTHER", barcode="999", buy_price=9000),
    ]
    row = {"product_name": "اسم مختلف", "sku": "SM-95", "barcode": "100200"}

    matches = PurchaseInvoiceService._product_candidates(row, products)

    assert matches[0]["id"] == 1
    assert matches[0]["score"] == 1.0
    assert matches[0]["reason"] == "barcode"


def test_purchase_product_matching_normalizes_arabic_names():
    from modules.workspace.services.purchase_invoice_service import PurchaseInvoiceService

    products = [
        SimpleNamespace(id=7, name="كريم العناية", sku=None, barcode=None, buy_price=5000),
    ]
    row = {"product_name": "كـريمُ العناية", "sku": None, "barcode": None}

    matches = PurchaseInvoiceService._product_candidates(row, products)

    assert matches[0]["id"] == 7
    assert matches[0]["score"] >= 0.97


def test_purchase_structured_table_parser_preserves_qty_price_and_totals():
    from modules.workspace.services.purchase_invoice_service import PurchaseInvoiceService

    rows, invoice = PurchaseInvoiceService._parse_table({
        "headers": ["product_name", "sku", "barcode", "quantity", "unit_price", "line_total"],
        "rows": [["منتج أ", "A-1", "123", 3, 15000, 45000]],
        "row_metadata": [{"confidence": 0.97, "source_page": 2}],
        "supplier_name": "شركة المورد",
        "supplier_invoice_no": "INV-20",
        "purchase_totals": {"discount_value": 5000, "shipping_extra": 2000, "grand_total": 42000},
    })

    assert rows[0]["quantity"] == 3
    assert rows[0]["unit_price"] == 15000
    assert rows[0]["line_total"] == 45000
    assert rows[0]["confidence"] == 0.97
    assert invoice["supplier_name"] == "شركة المورد"
    assert invoice["grand_total"] == 42000


def test_purchase_summary_blocks_ambiguous_rows_and_checks_grand_total():
    from modules.workspace.services.purchase_invoice_service import PurchaseInvoiceService

    analysis = {
        "supplier": {"source_name": "المورد", "decision": "create_new"},
        "invoice": {"discount_value": 0, "shipping_extra": 0, "declared_grand_total": 20000},
        "validation": {"blocking": []},
        "rows": [{
            "decision": "review",
            "quantity": 2,
            "unit_price": 5000,
            "line_total": 10000,
        }],
    }

    summary = PurchaseInvoiceService._summarize(analysis)

    assert summary["ready"] is False
    assert summary["review_rows"] == 1
    assert any("تحتاج قرار" in message for message in summary["blocking"])
    assert any("لا يساوي" in message for message in summary["blocking"])


def test_purchase_vision_validation_accepts_balanced_invoice():
    from modules.workspace.services.document_intelligence.purchase_invoice_vision_service import (
        PurchaseInvoiceVisionService,
    )

    result = PurchaseInvoiceVisionService.validate_payload({
        "rows": [{
            "product_name": "منتج",
            "quantity": 2,
            "unit_price": 10000,
            "line_total": 20000,
            "confidence": 0.96,
        }],
        "discount_value": 1000,
        "shipping_extra": 500,
        "grand_total": 19500,
    })

    assert result["ok"] is True
    assert result["blocking"] == []
    assert result["calculated"]["grand_total"] == 19500


def test_purchase_recipe_has_read_match_review_progress():
    from modules.workspace.recipes.purchase_invoice_recipe import PURCHASE_INVOICE_RECIPE

    step_ids = ["start", "read_purchase_foundation", "match_purchase_entities", "complete"]
    values = [PURCHASE_INVOICE_RECIPE["steps"][step]["avatar"]["progress"] for step in step_ids]

    assert values == sorted(values)
    assert PURCHASE_INVOICE_RECIPE["steps"]["match_purchase_entities"]["handler"] == "purchase_analysis.run"
    assert values[-1] == 100


def test_purchase_confirmation_survives_session_refresh_normalization():
    from modules.workspace.services.window_orchestrator import WindowOrchestrator

    windows = [{
        "id": "win-purchase-approval",
        "type": "approval_panel",
        "props": {"action": "purchase_posting", "analysisId": "purchase-analysis-1"},
    }]
    session = SimpleNamespace(
        workflow_type="purchase_invoice",
        status="completed",
        get_metadata=lambda: {"purchase_invoice_analysis": {"id": "purchase-analysis-1"}},
        get_windows=lambda: windows,
        set_windows=lambda value: windows.__setitem__(slice(None), value),
    )

    normalized = WindowOrchestrator.normalize_windows(session)

    assert normalized == windows
    assert normalized[0]["props"]["action"] == "purchase_posting"


def test_purchase_quantity_and_price_correction_recalculates_row(monkeypatch):
    import modules.workspace.services.purchase_invoice_service as module

    metadata = {
        "purchase_invoice_analysis": {
            "id": "analysis-values-1",
            "supplier": {"source_name": "المورد", "decision": "create_new"},
            "invoice": {"currency": "IQD", "discount_value": 0, "shipping_extra": 0, "declared_grand_total": 30000},
            "validation": {"invoice_blocking": []},
            "posting": {"status": "not_posted"},
            "rows": [{
                "row_index": 1,
                "decision": "create_new",
                "status": "invalid",
                "quantity": 0,
                "unit_price": 0,
                "line_total": 0,
                "validation": ["الكمية غير صحيحة"],
            }],
        }
    }
    windows = []

    class _Session:
        id = "session-values-1"

        def get_metadata(self):
            return metadata

        def set_metadata(self, value):
            metadata.clear()
            metadata.update(value)

        def get_windows(self):
            return windows

        def set_windows(self, value):
            windows[:] = value

    monkeypatch.setattr(module.db, "session", SimpleNamespace(commit=lambda: None))
    monkeypatch.setattr(module.event_bus, "emit_event", lambda *args, **kwargs: None)

    analysis = module.PurchaseInvoiceService.update_row_values(
        _Session(), "analysis-values-1", 1, 3, 10000, product_name="شاشة سمارت مصححة"
    )

    row = analysis["rows"][0]
    assert row["product_name"] == "شاشة سمارت مصححة"
    assert row["quantity"] == 3
    assert row["unit_price"] == 10000
    assert row["line_total"] == 30000
    assert row["validation"] == []
    assert analysis["summary"]["ready"] is True


def test_purchase_usd_price_is_converted_to_iqd_at_1350(monkeypatch):
    import modules.workspace.services.purchase_invoice_service as module

    metadata = {
        "purchase_invoice_analysis": {
            "id": "analysis-usd-1",
            "supplier": {"source_name": "المورد", "decision": "create_new"},
            "invoice": {"currency": "IQD", "discount_value": 0, "shipping_extra": 0},
            "validation": {"invoice_blocking": []},
            "posting": {"status": "not_posted"},
            "rows": [{
                "row_index": 1,
                "decision": "create_new",
                "status": "new_product",
                "product_name": "منتج بالدولار",
                "quantity": 1,
                "unit_price": 1,
                "line_total": 1,
                "validation": [],
            }],
        }
    }
    windows = []

    class _Session:
        id = "session-usd-1"

        def get_metadata(self):
            return metadata

        def set_metadata(self, value):
            metadata.clear()
            metadata.update(value)

        def get_windows(self):
            return windows

        def set_windows(self, value):
            windows[:] = value

    monkeypatch.setattr(module.db, "session", SimpleNamespace(commit=lambda: None))
    monkeypatch.setattr(module.event_bus, "emit_event", lambda *args, **kwargs: None)

    analysis = module.PurchaseInvoiceService.update_row_values(
        _Session(), "analysis-usd-1", 1, 2, 0, unit_price_usd="12.50"
    )

    row = analysis["rows"][0]
    assert row["unit_price"] == 16875
    assert row["line_total"] == 33750
    assert row["unit_price_usd"] == "12.50"
    assert row["price_currency"] == "USD"
    assert row["exchange_rate"] == 1350
    assert analysis["summary"]["grand_total"] == 33750


def test_purchase_supplier_can_be_corrected_to_existing_supplier(monkeypatch):
    import modules.workspace.services.purchase_invoice_service as module

    metadata = {
        "purchase_invoice_analysis": {
            "id": "analysis-supplier-1",
            "supplier": {"source_name": "اسم مقروء خطأ", "decision": "create_new"},
            "invoice": {"currency": "IQD", "discount_value": 0, "shipping_extra": 0},
            "validation": {"invoice_blocking": []},
            "posting": {"status": "not_posted"},
            "rows": [{
                "row_index": 1,
                "decision": "create_new",
                "status": "new_product",
                "product_name": "منتج",
                "quantity": 1,
                "unit_price": 1000,
                "line_total": 1000,
                "validation": [],
            }],
        }
    }
    windows = []

    class _Session:
        id = "session-supplier-1"

        def get_metadata(self):
            return metadata

        def set_metadata(self, value):
            metadata.clear()
            metadata.update(value)

        def get_windows(self):
            return windows

        def set_windows(self, value):
            windows[:] = value

    supplier = SimpleNamespace(id=7, name="شركة الزهراء", phone="07700000000")
    monkeypatch.setattr(
        module,
        "Supplier",
        SimpleNamespace(query=SimpleNamespace(get=lambda supplier_id: supplier if supplier_id == 7 else None)),
    )
    monkeypatch.setattr(module.db, "session", SimpleNamespace(commit=lambda: None))
    monkeypatch.setattr(module.event_bus, "emit_event", lambda *args, **kwargs: None)

    analysis = module.PurchaseInvoiceService.set_supplier(
        _Session(), "analysis-supplier-1", supplier_id=7
    )

    assert analysis["supplier"]["decision"] == "use_existing"
    assert analysis["supplier"]["matched"]["id"] == 7
    assert analysis["supplier"]["source_name"] == "شركة الزهراء"
    assert analysis["supplier"]["original_source_name"] == "اسم مقروء خطأ"
    assert analysis["summary"]["ready"] is True
