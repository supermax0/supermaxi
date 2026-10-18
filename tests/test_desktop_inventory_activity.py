"""Inventory log reads actual evidence; no migration, writes or guessed balances."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import event, inspect

from tests.test_smart_inventory_audit import audit_workspace  # noqa: F401


def _movement(f, *, branch=0, product=0, details=None, source="invoice", quantity=2):
    import json
    from models.stock_movement import StockMovement
    row = StockMovement(movement_key=str(uuid4()), movement_type="sale", direction="out",
                        product_id=f["products"][product].id, branch_id=f["branches"][branch].id,
                        quantity=quantity, unit_cost=123, total_cost=123 * quantity,
                        source_type=source, source_id=919, details_json=json.dumps(details or {}),
                        created_at=datetime(2025, 10, 11, 22, 0))
    f["db"].session.add(row)
    f["db"].session.flush()
    return row


def _audit(f, movement=None, *, before=10, after=8, delta=-2):
    from models.inventory_audit import InventoryQuantityAudit
    row = InventoryQuantityAudit(event_key=uuid4().hex, movement_id=movement.id if movement else None,
            product_id=f["products"][0].id, branch_id=f["branches"][0].id, operation="database_guard",
            before_quantity=before, after_quantity=after, delta_quantity=delta,
            employee_id=f["admin"].id, employee_name="المخزن", created_at=datetime(2025, 10, 11, 22, 0))
    f["db"].session.add(row)
    return row


def _grant(f, *permissions):
    from models.role import Permission, Role
    role = Role(name=uuid4().hex)
    for name in permissions:
        permission = Permission.query.filter_by(name=name).first()
        if not permission:
            permission = Permission(name=name)
        role.permissions.append(permission)
    f["staff"].roles = [role]
    f["db"].session.commit()


def test_log_deduplicates_linked_audits_and_reads_without_mutations(audit_workspace):
    f = audit_workspace
    row = _movement(f)
    _audit(f, row)
    _audit(f, before=8, after=9, delta=1)
    f["db"].session.commit()
    statements = []
    bind = f["db"].session.get_bind()
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = f["call"]("/api/v1/desktop/inventory-activity?q=TV55&from=2025-10-12&to=2025-10-12")
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert result.status_code == 200, result.get_json()
    data = result.get_json()["data"]
    assert data["total"] == 2
    entry = next(x for x in data["items"] if x["record_kind"] == "movement")
    assert (entry["before"], entry["after"]) == (10, 8)
    assert entry["actor_name"] == "المخزن" and entry["total_cost"] == 246
    assert entry["source_id"] is None and entry["can_open_source"] is False
    assert not {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"} & set(statements)
    assert f["stocks"][0].quantity == 12


def test_permissions_scope_and_cost_redaction_are_live(audit_workspace):
    f = audit_workspace
    _movement(f)
    _movement(f, branch=1, product=1)
    f["db"].session.commit()
    assert f["call"]("/api/v1/desktop/inventory-activity", employee=f["staff"]).status_code == 403
    _grant(f, "manage_inventory")
    data = f["call"]("/api/v1/desktop/inventory-activity", employee=f["staff"]).get_json()["data"]
    assert {x["branch_id"] for x in data["items"]} == {f["branches"][0].id}
    assert data["can_view_cost"] is False and all("unit_cost" not in x and "total_cost" not in x for x in data["items"])
    assert f["call"](f"/api/v1/desktop/inventory-activity?branch_id={f['branches'][1].id}", employee=f["staff"]).status_code == 403
    assert f["call"]("/api/v1/desktop/inventory-activity", session_tenant="other-company").status_code == 403
    f["staff"].is_active = False
    f["db"].session.commit()
    assert f["call"]("/api/v1/desktop/inventory-activity", employee=f["staff"]).status_code == 401


def test_option_and_ambiguous_balances_are_not_reconstructed(audit_workspace):
    f = audit_workspace
    option = _movement(f, details={"variant_color": "اللون: أسود / المقاس: L"})
    _audit(f, option)
    ambiguous = _movement(f)
    _audit(f, ambiguous)
    _audit(f, ambiguous)
    f["db"].session.commit()
    data = f["call"]("/api/v1/desktop/inventory-activity?direction=out&from=2025-10-12&to=2025-10-12").get_json()["data"]
    assert data["total"] == 2
    assert all(x["before"] is None and x["after"] is None and x["balance_basis"] == "unknown" for x in data["items"])
    assert all(x["actor_name"] == "المخزن" for x in data["items"])


def test_missing_log_schema_is_reported_without_creating_it(audit_workspace):
    f = audit_workspace
    from models.inventory_audit import InventoryQuantityAudit, InventoryStockSnapshot
    from models.stock_movement import StockMovement
    bind = f["db"].session.get_bind()
    for table in (InventoryStockSnapshot.__table__, InventoryQuantityAudit.__table__, StockMovement.__table__):
        table.drop(bind)
    result = f["call"]("/api/v1/desktop/inventory-activity")
    assert result.status_code == 200
    assert result.get_json()["data"]["available"] is False
    assert "stock_movement" not in inspect(bind).get_table_names()


def test_filters_paginate_and_reject_invalid_ranges(audit_workspace):
    f = audit_workspace
    for _ in range(3):
        _movement(f)
    f["db"].session.commit()
    first = f["call"]("/api/v1/desktop/inventory-activity?page_size=1&direction=out").get_json()["data"]
    second = f["call"]("/api/v1/desktop/inventory-activity?page_size=1&direction=out&page=2").get_json()["data"]
    assert first["total"] == second["total"] == 3 and first["items"][0]["id"] != second["items"][0]["id"]
    for query in ("page=0", "page_size=101", "direction=side", "from=2026-10-13&to=2026-10-12", "from=2026-02-30",
                  "from=0001-01-01", "to=9999-12-31", "product_id=" + "1" * 5000):
        assert f["call"]("/api/v1/desktop/inventory-activity?" + query).status_code == 400
    _movement(f, branch=1, product=1)
    f["db"].session.commit()
    data = f["call"](f"/api/v1/desktop/inventory-activity?direction=out&product_id={f['products'][0].id}").get_json()["data"]
    assert data["total"] == 4 and {row["branch_id"] for row in data["items"]} == {branch.id for branch in f["branches"]}


def test_source_links_check_document_branch_and_inconsistent_proof(audit_workspace):
    f = audit_workspace
    from models.invoice import Invoice
    from models.customer import Customer
    customer = Customer(name="عميل الحركة", phone="07001234567", branch_id=f["branches"][0].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    local = Invoice(customer_id=customer.id, customer_name=customer.name, total=200, branch_id=f["branches"][0].id)
    foreign = Invoice(customer_id=customer.id, customer_name=customer.name, total=200, branch_id=f["branches"][1].id)
    f["db"].session.add_all([local, foreign])
    f["db"].session.flush()
    one, two = _movement(f), _movement(f)
    one.source_id, two.source_id = local.id, foreign.id
    _audit(f, one, before=10, after=5, delta=-5)
    f["db"].session.commit()
    _grant(f, "manage_inventory", "view_orders", "view_orders_placed")
    data = f["call"]("/api/v1/desktop/inventory-activity?direction=out", employee=f["staff"]).get_json()["data"]
    first = next(row for row in data["items"] if row["id"] == one.id)
    second = next(row for row in data["items"] if row["id"] == two.id)
    assert first["can_open_source"] and first["source_id"] == local.id
    assert first["before"] is None and first["after"] is None
    assert not second["can_open_source"] and second["source_id"] is None
    _grant(f, "manage_inventory", "view_orders")
    data = f["call"]("/api/v1/desktop/inventory-activity?direction=out", employee=f["staff"]).get_json()["data"]
    assert all(not row["can_open_source"] and row["source_id"] is None for row in data["items"])


def test_product_projection_is_not_another_physical_movement(audit_workspace):
    f = audit_workspace
    physical = _movement(f)
    _audit(f, physical)
    mirror = _audit(f)
    mirror.set_metadata({"database_guard": True, "scope": "product.quantity"})
    f["db"].session.commit()
    data = f["call"]("/api/v1/desktop/inventory-activity?from=2025-10-12&to=2025-10-12").get_json()["data"]
    assert data["total"] == 1 and data["items"][0]["id"] == physical.id


def test_reports_include_all_filtered_rows_and_protect_costs_and_spreadsheet_cells(audit_workspace):
    import csv
    import io
    f = audit_workspace
    for _ in range(3):
        _movement(f)
    f["products"][0].name = "=SUM(1,2)"
    f["products"][0].sku = "000123"
    f["db"].session.commit()
    _grant(f, "manage_inventory")
    filters = "?page=2&page_size=1&from=2025-10-12&to=2025-10-12"
    result = f["call"]("/api/v1/desktop/inventory-activity/export" + filters, employee=f["staff"])
    assert result.status_code == 200, result.get_json()
    rows = list(csv.reader(io.StringIO(result.get_json()["data"]["content"].lstrip("\ufeff"))))
    assert len(rows) == 4 and "قيمة الحركة بالتكلفة" not in rows[0]
    assert all(row[1] == "'=SUM(1,2)" and row[2] == "'000123" and row[8] == row[9] == "—" for row in rows[1:])
    html = f["call"]("/api/v1/desktop/inventory-activity/print" + filters, employee=f["staff"])
    assert html.status_code == 200
    text = html.get_data(as_text=True)
    assert text.count("=SUM(1,2)") == 3 and "قيمة الحركة</th>" not in text
    assert f["stocks"][0].quantity == 12


def test_large_dinar_values_remain_exact_in_json_csv_and_print(audit_workspace):
    f = audit_workspace
    movement = _movement(f)
    movement.total_cost = 1000000000000000001
    f["db"].session.commit()
    filters = "?direction=out&from=2025-10-12&to=2025-10-12"
    data = f["call"]("/api/v1/desktop/inventory-activity" + filters).get_json()["data"]
    assert data["items"][0]["total_cost"] == "1000000000000000001"
    content = f["call"]("/api/v1/desktop/inventory-activity/export" + filters).get_json()["data"]["content"]
    assert "'1000000000000000001" in content
    html = f["call"]("/api/v1/desktop/inventory-activity/print" + filters).get_data(as_text=True)
    assert "1,000,000,000,000,000,001" in html


def test_automatic_uncosted_capture_does_not_claim_free_stock(audit_workspace):
    import json
    f = audit_workspace
    movement = _movement(f, source="direct_stock_change")
    movement.movement_type = "unclassified_adjustment"
    movement.details_json = json.dumps({"auto_captured": True})
    movement.unit_cost = movement.total_cost = 0
    f["db"].session.commit()
    data = f["call"]("/api/v1/desktop/inventory-activity?direction=out").get_json()["data"]
    assert data["items"][0]["unit_cost"] is None and data["items"][0]["total_cost"] is None


def test_trade_in_receipt_opens_its_invoice_not_its_receipt_number(audit_workspace):
    f = audit_workspace
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.trade_in_receipt import TradeInReceipt
    customer = Customer(name="عميل الاستبدال", phone="07009876543", branch_id=f["branches"][0].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, total=200, branch_id=f["branches"][0].id)
    f["db"].session.add(invoice)
    f["db"].session.flush()
    item = OrderItem(invoice_id=invoice.id, product_id=f["products"][0].id, product_name=f["products"][0].name,
                     quantity=1, price=200, cost=100, total=200, sale_mode="exchange")
    f["db"].session.add(item)
    f["db"].session.flush()
    receipt = TradeInReceipt(invoice_id=invoice.id, order_item_id=item.id, source_product_name="استبدال",
                            replacement_product_id=f["products"][2].id, branch_id=f["branches"][0].id, status="received")
    f["db"].session.add(receipt)
    f["db"].session.flush()
    movement = _movement(f, source="trade_in_receipt", product=2, quantity=1)
    movement.direction, movement.source_id = "in", receipt.id
    f["db"].session.commit()
    data = f["call"]("/api/v1/desktop/inventory-activity?from=2025-10-12&to=2025-10-12").get_json()["data"]
    row = data["items"][0]
    assert row["source_id"] == receipt.id and row["document_id"] == invoice.id and row["document_kind"] == "invoice"
    assert row["operation_label"] == "استلام استبدال" and row["can_open_source"]
    _grant(f, "manage_inventory")
    data = f["call"]("/api/v1/desktop/inventory-activity?from=2025-10-12&to=2025-10-12", employee=f["staff"]).get_json()["data"]
    assert data["items"][0]["source_id"] is None and data["items"][0]["document_id"] is None
