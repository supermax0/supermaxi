from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask

from extensions import db


def _movement(mid, movement_type, direction, branch_id, quantity, source_id, line_id, at):
    return SimpleNamespace(
        id=mid,
        movement_type=movement_type,
        direction=direction,
        branch_id=branch_id,
        quantity=quantity,
        source_id=source_id,
        source_line_id=line_id,
        source_type="stock_transfer" if movement_type.startswith("transfer_") else "invoice",
        created_at=at,
    )


def test_piece_identity_survives_transfer_between_branches():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    now = datetime.utcnow()
    product = SimpleNamespace(id=7, name="منتج تجريبي", barcode="P-7", created_at=now - timedelta(days=10))
    branches = [
        {"branch_id": 1, "opening": 2, "actual": 1},
        {"branch_id": 2, "opening": 0, "actual": 1},
    ]
    movements = [
        _movement(11, "transfer_send", "out", 1, 1, 88, 901, now),
        _movement(12, "transfer_receive", "in", 2, 1, 88, 901, now + timedelta(minutes=3)),
    ]

    result = InventoryForensicsService._unit_traces(product, branches, movements, {1: 1, 2: 1})

    moved = next(item for item in result["items"] if len(item["events"]) == 2)
    assert moved["trace_id"].startswith("P7-B1-OPEN-")
    assert moved["current_branch_id"] == 2
    assert moved["status"] == "in_stock"
    assert [event["type"] for event in moved["events"]] == ["transfer_send", "transfer_receive"]
    assert result["anomalies"] == []


def test_piece_identity_survives_order_return():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    now = datetime.utcnow()
    product = SimpleNamespace(id=9, name="سيروم", barcode="S-9", created_at=now - timedelta(days=2))
    branches = [{"branch_id": 4, "opening": 1, "actual": 1}]
    movements = [
        _movement(21, "order_deduct", "out", 4, 1, 300, 44, now),
        _movement(22, "order_restore", "in", 4, 1, 300, 44, now + timedelta(hours=1)),
    ]

    result = InventoryForensicsService._unit_traces(product, branches, movements, {4: 1})

    assert result["total"] == 1
    assert result["items"][0]["status"] == "in_stock"
    assert len(result["items"][0]["events"]) == 2
    assert result["anomalies"] == []


def test_unexplained_missing_piece_is_flagged_critical():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    product = SimpleNamespace(id=12, name="كريم", barcode=None, created_at=datetime.utcnow())
    result = InventoryForensicsService._unit_traces(
        product,
        [{"branch_id": 2, "opening": 3, "actual": 2}],
        [],
        {2: 2},
    )

    assert result["missing"] == 1
    assert any(item["status"] == "missing_unexplained" for item in result["items"])
    assert result["anomalies"][0]["severity"] == "critical"


@pytest.fixture()
def trigger_app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        db.session.execute(db.text("CREATE TABLE product (id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL DEFAULT 0)"))
        db.session.execute(db.text("CREATE TABLE branch_stock (id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, product_id INTEGER NOT NULL, quantity INTEGER NOT NULL DEFAULT 0)"))
        db.session.commit()
        yield app
        db.session.remove()


def test_database_guard_catches_legacy_direct_quantity_writes(trigger_app):
    from utils.inventory_audit_trail import ensure_inventory_audit_schema

    with trigger_app.app_context():
        ensure_inventory_audit_schema()
        db.session.execute(db.text("INSERT INTO product (id, quantity) VALUES (1, 5)"))
        db.session.execute(db.text("INSERT INTO branch_stock (id, branch_id, product_id, quantity) VALUES (1, 3, 1, 5)"))
        db.session.commit()
        db.session.execute(db.text("UPDATE branch_stock SET quantity = 4 WHERE id = 1"))
        db.session.commit()

        row = db.session.execute(db.text(
            "SELECT before_quantity, delta_quantity, after_quantity, operation "
            "FROM inventory_quantity_audit WHERE product_id = 1 AND branch_id = 3 "
            "ORDER BY id DESC LIMIT 1"
        )).mappings().one()

        assert row["before_quantity"] == 5
        assert row["delta_quantity"] == -1
        assert row["after_quantity"] == 4
        assert row["operation"] == "database_guard"


def test_recipe_opens_professional_inventory_investigator():
    from modules.workspace.recipes.inventory_forensics_recipe import INVENTORY_FORENSICS_RECIPE

    assert INVENTORY_FORENSICS_RECIPE["steps"]["open_forensics"]["handler"] == "inventory_forensics.open"
    assert INVENTORY_FORENSICS_RECIPE["steps"]["complete"]["avatar"]["progress"] == 100


def test_root_cause_explains_exact_direct_quantity_change():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    diagnosis = InventoryForensicsService._root_cause_analysis(
        movement_rows=[{
            "id": "audit-15",
            "source": {"kind": "database_trigger"},
            "delta": -1,
            "before": 26,
            "after": 25,
            "created_at": "2026-08-02T09:00:00",
            "request_path": "/inventory/adjust",
        }],
        snapshot_comparisons=[],
        reconciliations=[],
        unit_traces={"missing": 1},
        product_quantity=25,
        all_branch_total=25,
    )

    assert diagnosis["primary"]["code"] == "direct_database_write"
    assert diagnosis["primary"]["confidence"] == 99
    assert any("26" in evidence and "25" in evidence for evidence in diagnosis["primary"]["evidence"])
    assert any("/inventory/adjust" in evidence for evidence in diagnosis["primary"]["evidence"])


def test_root_cause_explains_loss_between_scans_without_sale():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    diagnosis = InventoryForensicsService._root_cause_analysis(
        movement_rows=[],
        snapshot_comparisons=[{
            "has_baseline": True,
            "is_balanced": False,
            "difference": -1,
            "branch_name": "الفرع الرئيسي",
            "baseline_quantity": 26,
            "documented_delta": 0,
            "expected": 26,
            "actual": 25,
        }],
        reconciliations=[],
        unit_traces={"missing": 1},
        product_quantity=25,
        all_branch_total=25,
    )

    assert diagnosis["primary"]["code"] == "snapshot_unexplained_change"
    assert "بلا حركة خروج" in diagnosis["primary"]["title"]
    assert "يستبعد البيع المسجل" in diagnosis["primary"]["explanation"]


def test_root_cause_explains_transfer_stuck_between_branches():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    diagnosis = InventoryForensicsService._root_cause_analysis(
        movement_rows=[{
            "id": 1,
            "movement_type": "transfer_send",
            "quantity": 4,
            "source_id": 77,
            "source_line_id": 8,
            "source": {"kind": "stock_transfer", "number": "TR-77", "from_branch": "بغداد", "to_branch": "البصرة"},
        }, {
            "id": 2,
            "movement_type": "transfer_receive",
            "quantity": 3,
            "source_id": 77,
            "source_line_id": 8,
            "source": {"kind": "stock_transfer", "number": "TR-77", "from_branch": "بغداد", "to_branch": "البصرة"},
        }],
        snapshot_comparisons=[],
        reconciliations=[],
        unit_traces={"missing": 1},
        product_quantity=10,
        all_branch_total=10,
    )

    assert diagnosis["primary"]["code"] == "transfer_not_completed"
    assert any("العالق 1" in evidence for evidence in diagnosis["primary"]["evidence"])


def test_root_cause_reports_healthy_when_no_gap_exists():
    from modules.workspace.services.inventory_forensics_service import InventoryForensicsService

    diagnosis = InventoryForensicsService._root_cause_analysis(
        movement_rows=[],
        snapshot_comparisons=[],
        reconciliations=[{"is_balanced": True}],
        unit_traces={"missing": 0},
        product_quantity=8,
        all_branch_total=8,
    )

    assert diagnosis["status"] == "explained_healthy"
    assert diagnosis["primary"]["code"] == "no_unexplained_loss"
