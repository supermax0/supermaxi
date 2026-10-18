"""Acceptance coverage for branch isolation and independent transfer catalogs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from werkzeug.exceptions import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_branch_scope_v3_{os.getpid()}"


def test_branch_scope_transfer_clone_and_employee_history():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g, session
    from models.branch import Branch, StockTransfer, StockTransferLine
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.inventory_lot import InventoryLot
    from routes.stock_transfers import _apply_transfer_movements
    from routes.pos import create_order
    from utils.branch_context import init_branch_context
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.branch_sales import active_branches_for_sales
    from utils.branch_scope import resolve_write_branch_id
    from utils.branch_stock_service import get_branch_stock, set_branch_stock

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        ensure_branch_schema()
        main = get_default_branch()
        second = Branch(code="B2", name="الفرع الثاني", is_active=True, is_default=False)
        admin = Employee(name="Admin", username=f"admin-{os.getpid()}", password="x", role="admin")
        staff = Employee(name="Staff", username=f"staff-{os.getpid()}", password="x", role="cashier", branch_id=main.id)
        customer = Customer(branch_id=main.id, name="Branch Customer", phone="07700000001")
        product = Product(
            branch_id=main.id,
            name="Branch Product",
            barcode="SAME-BARCODE",
            buy_price=100,
            sale_price=200,
            quantity=5,
            active=True,
        )
        db.session.add_all([second, admin, staff, customer, product])
        db.session.flush()
        set_branch_stock(main.id, product.id, 5)
        # The fixture's five opening pieces have a known acquisition cost.
        # Transfers now require the physical balance and its FIFO evidence.
        db.session.add(InventoryLot(product_id=product.id,branch_id=main.id,
            quantity=5,remaining_quantity=5,unit_cost=100))
        db.session.flush()

        invoice = Invoice(
            branch_id=main.id,
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=staff.id,
            total=200,
            status="تم الطلب",
            payment_status="غير مسدد",
        )
        db.session.add(invoice)
        transfer = StockTransfer(
            transfer_no=f"TV3-{os.getpid()}",
            from_branch_id=main.id,
            to_branch_id=second.id,
            status="draft",
            created_by_id=admin.id,
        )
        db.session.add(transfer)
        db.session.flush()
        line = StockTransferLine(transfer_id=transfer.id, product_id=product.id, quantity=2)
        db.session.add(line)
        db.session.flush()

        _apply_transfer_movements(transfer, "send")
        _apply_transfer_movements(transfer, "receive")
        db.session.commit()

        destination = Product.query.execution_options(skip_branch_scope=True).get(line.destination_product_id)
        assert destination is not None
        assert destination.id != product.id
        assert destination.branch_id == second.id
        assert destination.catalog_group_id == product.catalog_group_id
        assert destination.barcode == product.barcode
        assert get_branch_stock(main.id, product.id) == 3
        assert get_branch_stock(second.id, destination.id) == 2
        assert InventoryLot.query.filter_by(product_id=product.id,branch_id=main.id).one().remaining_quantity==3
        assert InventoryLot.query.filter_by(product_id=destination.id,branch_id=second.id).one().unit_cost==100
        destination_price = destination.sale_price
        product.sale_price = 999
        staff.branch_id = second.id
        db.session.commit()
        assert destination.sale_price == destination_price
        assert invoice.branch_id == main.id

        with app.test_request_context("/inventory"):
            g.tenant = TENANT
            session.update(user_id=admin.id, role="admin", tenant_slug=TENANT,
                           view_all_branches=False, branch_id=main.id)
            init_branch_context()
            assert {row.id for row in Product.query.all()} == {product.id}
            # The dashboard stays scoped to the selected branch, while the
            # explicit cross-branch fulfillment picker still lists all active
            # company branches.
            assert {row.id for row in active_branches_for_sales()} == {main.id, second.id}
            try:
                resolve_write_branch_id({"branch_id": second.id})
                assert False, "ordinary admin writes must follow the dashboard branch"
            except HTTPException as exc:
                assert exc.code == 403
            assert resolve_write_branch_id(
                {"branch_id": second.id},
                allow_admin_any_branch=True,
            ) == second.id

        with app.test_request_context("/inventory"):
            g.tenant = TENANT
            session.update(user_id=admin.id, role="admin", tenant_slug=TENANT,
                           view_all_branches=False, branch_id=second.id)
            init_branch_context()
            assert {row.id for row in Product.query.all()} == {destination.id}

        with app.test_request_context("/inventory"):
            g.tenant = TENANT
            session.update(user_id=admin.id, role="admin", tenant_slug=TENANT,
                           view_all_branches=True)
            session.pop("branch_id", None)
            init_branch_context()
            assert {row.id for row in Product.query.all()} == {product.id, destination.id}
            assert resolve_write_branch_id({}) == main.id
            assert resolve_write_branch_id({"customer_id": customer.id}) == main.id
            assert resolve_write_branch_id({"product_id": destination.id}) == second.id
            assert resolve_write_branch_id({"branch_id": second.id}) == second.id

        destination_customer = Customer(
            branch_id=second.id,
            name="Second Branch Customer",
            phone="07700000002",
        )
        db.session.add(destination_customer)
        db.session.commit()
        destination_customer_id = destination_customer.id
        destination_product_id = destination.id

        payload = {
            "branch_id": second.id,
            "customer_id": destination_customer_id,
            "items": [{"product_id": destination_product_id, "qty": 1, "price": destination.sale_price}],
        }
        with app.test_request_context("/pos/create-order", method="POST", json=payload):
            g.tenant = TENANT
            session.update(user_id=admin.id, role="admin", tenant_slug=TENANT,
                           view_all_branches=False, branch_id=main.id)
            init_branch_context()
            response = create_order()
            status = 200
            if isinstance(response, tuple):
                response, status = response
            assert status == 200
            created = response.get_json()
            assert created["success"] is True
            created_invoice = Invoice.query.execution_options(skip_branch_scope=True).get(created["invoice_id"])
            created_item = OrderItem.query.filter_by(invoice_id=created_invoice.id).one()
            assert created_invoice.branch_id == second.id
            assert created_item.fulfillment_branch_id == second.id

        with app.test_request_context("/inventory", method="POST"):
            g.tenant = TENANT
            session.update(user_id=staff.id, role="cashier", tenant_slug=TENANT,
                           view_all_branches=False, branch_id=second.id)
            init_branch_context()
            try:
                resolve_write_branch_id({"branch_id": main.id})
                assert False, "staff branch override must be rejected"
            except HTTPException as exc:
                assert exc.code == 403

        tampered_payload = {
            "branch_id": main.id,
            "customer_id": customer.id,
            "items": [{"product_id": product.id, "qty": 1, "price": product.sale_price}],
        }
        with app.test_request_context("/pos/create-order", method="POST", json=tampered_payload):
            g.tenant = TENANT
            session.update(user_id=staff.id, role="cashier", tenant_slug=TENANT,
                           view_all_branches=False, branch_id=second.id)
            init_branch_context()
            try:
                response = create_order()
            except HTTPException as exc:
                assert exc.code == 403
            else:
                status = 200
                payload = response
                if isinstance(response, tuple):
                    payload, status = response
                assert status == 403, "POS must reject a staff attempt to deduct another branch"
                body = payload.get_json() if hasattr(payload, "get_json") else {}
                assert body.get("code") in ("BRANCH_NOT_ALLOWED", None) or "فرع" in str(body.get("error") or "")
