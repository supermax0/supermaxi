from types import SimpleNamespace


class _Query:
    def __init__(self, invoices):
        self.invoices = invoices

    def get(self, invoice_id):
        return self.invoices.get(int(invoice_id))


class _Analysis:
    id = "analysis-return-1"
    document_kind = "return_statement"
    status = "completed"

    def get_summary(self):
        return {"analysis_mode": "return"}


def _row(row_id, invoice_id, status="matched", order_number="210791"):
    return SimpleNamespace(
        id=row_id,
        row_index=1,
        matched_invoice_id=invoice_id,
        match_status=status,
        normalized_order_number=order_number,
        raw_order_number=order_number,
    )


def test_return_eligibility_accepts_only_confirmed_barcode_matches(monkeypatch):
    import modules.workspace.services.return_statement_service as module

    invoice = SimpleNamespace(
        id=21,
        status="جاري الشحن",
        payment_status="غير مسدد",
        barcode="210791",
        shipping_barcode=None,
        shipping_barcodes_json=None,
    )
    monkeypatch.setattr(module, "Invoice", SimpleNamespace(query=_Query({21: invoice})))
    monkeypatch.setattr(
        module.ReturnStatementService,
        "_rows",
        staticmethod(lambda _analysis_id: [
            _row("safe", 21),
            _row("review", 21, status="review"),
            _row("wrong-code", 21, order_number="999999"),
        ]),
    )

    safe, blocked = module.ReturnStatementService._eligible_rows(_Analysis())

    assert [item[0].id for item in safe] == ["safe"]
    assert len(blocked) == 2
    assert {item["row_id"] for item in blocked} == {"review", "wrong-code"}


def test_return_eligibility_blocks_already_returned_orders(monkeypatch):
    import modules.workspace.services.return_statement_service as module

    invoice = SimpleNamespace(
        id=22,
        status="راجع",
        payment_status="راجع",
        barcode="210792",
        shipping_barcode=None,
        shipping_barcodes_json=None,
    )
    monkeypatch.setattr(module, "Invoice", SimpleNamespace(query=_Query({22: invoice})))
    monkeypatch.setattr(
        module.ReturnStatementService,
        "_rows",
        staticmethod(lambda _analysis_id: [_row("returned", 22, order_number="210792")]),
    )

    safe, blocked = module.ReturnStatementService._eligible_rows(_Analysis())

    assert safe == []
    assert blocked[0]["reason"] == "الطلب راجع مسبقاً"


def test_return_approval_survives_session_window_normalization():
    from modules.workspace.services.window_orchestrator import WindowOrchestrator

    windows = [
        {
            "id": "win-return-approval",
            "type": "approval_panel",
            "props": {"action": "return_posting", "analysisId": "analysis-return-1"},
        }
    ]
    session = SimpleNamespace(
        workflow_type="return_statement",
        status="completed",
        get_metadata=lambda: {"last_courier_analysis": {"analysis_id": "analysis-return-1"}},
        get_windows=lambda: windows,
        set_windows=lambda value: windows.__setitem__(slice(None), value),
    )

    normalized = WindowOrchestrator.normalize_windows(session)

    assert normalized == windows
    assert normalized[0]["id"] == "win-return-approval"


def test_return_execution_uses_verified_lifecycle_and_posts_atomically(monkeypatch):
    import modules.workspace.services.return_statement_service as module

    class _PostingAnalysis(_Analysis):
        def __init__(self):
            self.status = "completed"
            self.updated_at = None
            self.summary = {"analysis_mode": "return"}

        def get_summary(self):
            return dict(self.summary)

        def set_summary(self, value):
            self.summary = dict(value)

    analysis = _PostingAnalysis()
    row = _row("safe", 23, order_number="210793")
    invoice = SimpleNamespace(
        id=23,
        status="جاري الشحن",
        payment_status="مسدد",
        paid_amount=100,
        shipping_company_id=None,
        total=100,
    )
    session = SimpleNamespace(id="session-return-1", get_windows=lambda: [])
    lifecycle_calls = []
    ledger_deltas = []
    committed = []

    monkeypatch.setattr(
        module.ReturnStatementService,
        "build_preview",
        staticmethod(lambda _analysis: {
            "safe_rows": 1,
            "blocked_rows": 0,
            "total_units": 2,
            "executed_at": None,
        }),
    )
    monkeypatch.setattr(
        module.ReturnStatementService,
        "_eligible_rows",
        staticmethod(lambda _analysis: ([(row, invoice, "210793")], [])),
    )

    def _return_order(order, barcode, return_branch_id=None):
        lifecycle_calls.append((order.id, barcode, return_branch_id))
        order.status = "راجع"
        order.payment_status = "راجع"
        order.paid_amount = 0
        return False, "تم الترجيع وإعادة المخزون"

    monkeypatch.setattr(module, "process_order_return", _return_order)
    monkeypatch.setattr(module, "_effective_paid_amount", lambda order: int(order.paid_amount or 0))
    monkeypatch.setattr(
        module,
        "append_payment_ledger_delta",
        lambda invoice_id, delta: ledger_deltas.append((invoice_id, delta)),
    )
    monkeypatch.setattr(module, "sync_delivery_expense_for_invoice", lambda _invoice: None)
    monkeypatch.setattr(
        module.InvoiceSnapshotAdapter,
        "from_invoice",
        staticmethod(lambda order: {"id": order.id, "status": order.status}),
    )
    monkeypatch.setattr(module, "log_mutation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.WindowOrchestrator, "close_window_types", lambda *args: None)
    monkeypatch.setattr(
        module,
        "CourierStatementAnalysisIssue",
        SimpleNamespace(query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(all=lambda: []))),
    )
    monkeypatch.setattr(module.CourierReadonlyAnalysisService, "_sync_windows", lambda *args: None)
    monkeypatch.setattr(module.event_bus, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "db",
        SimpleNamespace(
            session=SimpleNamespace(
                add=lambda _value: None,
                commit=lambda: committed.append(True),
                rollback=lambda: None,
            )
        ),
    )

    posting = module.ReturnStatementService.execute_approved(
        session,
        analysis,
        user_id=7,
    )

    assert lifecycle_calls == [(23, "210793", None)]
    assert ledger_deltas == [(23, -100)]
    assert committed == [True]
    assert analysis.status == "posted"
    assert posting["invoice_ids"] == [23]
    assert posting["total_units"] == 2


def test_return_recipe_has_monotonic_leon_progress():
    from modules.workspace.recipes.return_statement_recipe import RETURN_STATEMENT_RECIPE

    step_ids = [
        "start",
        "read_return_foundation",
        "run_return_analysis",
        "placeholder_barcode",
        "complete",
    ]
    progresses = [
        RETURN_STATEMENT_RECIPE["steps"][step_id]["avatar"]["progress"]
        for step_id in step_ids
    ]

    assert progresses == sorted(progresses)
    assert progresses[0] > 0
    assert progresses[-1] == 100


def test_ensure_window_persists_new_return_approval():
    from modules.workspace.services.window_orchestrator import WindowOrchestrator

    stored = []

    class _WindowSession:
        def get_windows(self):
            return [dict(item) for item in stored]

        def set_windows(self, value):
            stored[:] = value

    WindowOrchestrator.ensure_window(
        _WindowSession(),
        {
            "id": "win-return-confirm",
            "type": "approval_panel",
            "title": "موافقة تنفيذ كشف الراجع",
            "props": {"action": "return_posting", "analysisId": "analysis-return-1"},
        },
        "return_posting_approval",
    )

    assert len(stored) == 1
    assert stored[0]["type"] == "approval_panel"
    assert stored[0]["props"]["action"] == "return_posting"
