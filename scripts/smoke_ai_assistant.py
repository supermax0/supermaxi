"""Smoke checks for the Finora AI assistant.

Run from the project root:
    .\venv\Scripts\python.exe scripts\smoke_ai_assistant.py
"""
from __future__ import annotations

from pathlib import Path
import sys

from flask import g, render_template
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from extensions import db
from models.core.tenant import Tenant
from models.employee import Employee
from models.ai_assistant_control import AIActionItem, AIActionPlan
from models.branch import Branch
from models.product import Product
from utils.branch_stock_service import get_branch_stock

import utils.ai_assistant_service as svc


def _assert_excel_parser() -> None:
    files = sorted(Path(r"C:\Users\msi\Downloads").glob("inventory_audit_*.xlsx"))
    for file_path in files:
        parsed = svc.parse_inventory_audit_workbook(str(file_path))
        assert parsed["rows"], f"no rows parsed from {file_path}"
        assert not parsed["errors"], f"parse errors in {file_path}: {parsed['errors'][:3]}"
    print(f"excel parser ok ({len(files)} files)")


def _assert_order_detection() -> None:
    assert svc._detect_order_action("سدد الطلب 29") == "mark_paid"
    assert svc._extract_order_ids("ارجاع الطلب #15 باركود: ABC123") == [15]
    print("order detection ok")


def _assert_template_permissions() -> None:
    with app.test_request_context("/assistant/chat"):
        cashier = render_template(
            "assistant/chat.html",
            session={"role": "cashier"},
            assistant_permissions={
                "approve_ai_actions": False,
                "manage_ai_schedules": False,
                "view_ai_audit_logs": False,
            },
        )
        assert 'id="aiOverviewList"' not in cashier
        assert 'id="aiSaveScheduleBtn"' not in cashier
        admin = render_template(
            "assistant/chat.html",
            session={"role": "admin"},
            assistant_permissions={
                "approve_ai_actions": True,
                "manage_ai_schedules": True,
                "view_ai_audit_logs": True,
            },
        )
        assert 'id="aiOverviewList"' in admin
        assert 'id="aiSaveScheduleBtn"' in admin
        assert 'id="aiScheduleSeverity"' in admin
        assert 'id="aiScheduleActive"' in admin
    print("template permissions ok")


def _cleanup_probe_employee() -> None:
    ids = [
        row[0]
        for row in db.session.execute(
            text("SELECT id FROM employee WHERE username = 'ai_scope_probe'")
        ).fetchall()
    ]
    for employee_id in ids:
        session_ids = [
            row[0]
            for row in db.session.execute(
                text("SELECT id FROM ai_chat_session WHERE employee_id = :id"),
                {"id": employee_id},
            ).fetchall()
        ]
        for session_id in session_ids:
            db.session.execute(text("DELETE FROM ai_chat_message WHERE session_id = :id"), {"id": session_id})
            db.session.execute(text("DELETE FROM ai_uploaded_file WHERE session_id = :id"), {"id": session_id})
            plan_ids = [
                row[0]
                for row in db.session.execute(
                    text("SELECT id FROM ai_action_plan WHERE session_id = :id"),
                    {"id": session_id},
                ).fetchall()
            ]
            for plan_id in plan_ids:
                db.session.execute(text("DELETE FROM ai_tool_call_log WHERE plan_id = :id"), {"id": plan_id})
                db.session.execute(text("DELETE FROM ai_action_item WHERE plan_id = :id"), {"id": plan_id})
            db.session.execute(text("DELETE FROM ai_action_plan WHERE session_id = :id"), {"id": session_id})
        db.session.execute(text("DELETE FROM ai_chat_session WHERE employee_id = :id"), {"id": employee_id})
        db.session.execute(text("DELETE FROM message WHERE sender_id = :id OR receiver_id = :id"), {"id": employee_id})
        db.session.execute(text("DELETE FROM employee WHERE id = :id"), {"id": employee_id})
    db.session.commit()


def _assert_permissions_and_audit_plan() -> None:
    g.tenant = None
    tenant = Tenant.query.filter_by(is_active=True).first()
    assert tenant, "no active tenant found"
    tenant_slug = tenant.slug
    g.tenant = tenant_slug
    svc.ensure_ai_assistant_schema()
    _cleanup_probe_employee()

    old_call = svc._call_openai_narrative
    svc._call_openai_narrative = lambda message, snapshot, local_findings=None: (False, "local only")
    try:
        employee = Employee(
            name="AI Scope Probe",
            username="ai_scope_probe",
            password="x",
            role="cashier",
            is_active=True,
        )
        db.session.add(employee)
        db.session.flush()
        snapshot = svc.collect_system_snapshot(employee_id=employee.id)
        assert snapshot["financial"].get("restricted") is True
        assert snapshot["products"].get("restricted") is True
        result = svc.handle_chat_send(employee_id=employee.id, message="سدد الطلب 29")
        assert not result.get("action_plan")
        assert result["local_findings"]["order_plan"]["restricted"] is True
    finally:
        svc._call_openai_narrative = old_call
        _cleanup_probe_employee()

    plan = svc._build_audit_review_plan(
        audit_type="comprehensive",
        summary={"stock_imbalances_count": 2, "negative_margin_items_count": 1},
        employee_id=None,
        schedule_id=None,
    )
    db.session.flush()
    assert len(plan.items) == 2
    db.session.rollback()
    print(f"permission scope and review plan ok ({tenant_slug})")


def _assert_schedule_customization() -> None:
    g.tenant = None
    tenant = Tenant.query.filter_by(is_active=True).first()
    assert tenant, "no active tenant found"
    g.tenant = tenant.slug
    svc.ensure_ai_assistant_schema()
    schedule = svc.create_or_update_schedule(
        {
            "name": "AI Smoke Schedule",
            "audit_type": "inventory",
            "interval_minutes": 30,
            "severity_threshold": "critical",
            "is_active": False,
        },
        employee_id=None,
    )
    assert schedule.id
    assert schedule.audit_type == "inventory"
    assert schedule.interval_minutes == 30
    assert schedule.severity_threshold == "critical"
    assert schedule.is_active is False
    updated = svc.create_or_update_schedule(
        {
            "id": schedule.id,
            "name": "AI Smoke Schedule Updated",
            "audit_type": "unknown",
            "interval_minutes": "bad",
            "severity_threshold": "bad",
            "is_active": True,
        },
        employee_id=None,
    )
    assert updated.id == schedule.id
    assert updated.audit_type == "comprehensive"
    assert updated.interval_minutes == 1440
    assert updated.severity_threshold == "warning"
    assert updated.is_active is True
    db.session.execute(text("DELETE FROM ai_scheduled_audit WHERE id = :id"), {"id": schedule.id})
    db.session.commit()
    print("schedule customization ok")


def _assert_action_preflight() -> None:
    g.tenant = None
    tenant = Tenant.query.filter_by(is_active=True).first()
    assert tenant, "no active tenant found"
    g.tenant = tenant.slug
    svc.ensure_ai_assistant_schema()
    branch = Branch.query.first()
    product = Product.query.first()
    if not branch:
        branch = Branch(code="AI_SMOKE_BRANCH", name="AI Smoke Branch", is_active=True)
        db.session.add(branch)
        db.session.flush()
    if not product:
        product = Product(name="AI Smoke Product", buy_price=1, sale_price=1, quantity=0, active=True)
        db.session.add(product)
        db.session.flush()
    current = get_branch_stock(branch.id, product.id)
    plan = AIActionPlan(
        title="AI Smoke Preflight",
        plan_type="inventory_reconcile",
        status="approved",
        summary="smoke",
    )
    db.session.add(plan)
    db.session.flush()
    item = AIActionItem(
        plan_id=plan.id,
        item_type="stock_adjustment",
        title="AI Smoke Adjustment",
        target_type="branch_stock",
        target_id=product.id,
    )
    item.set_before({"branch_stock": current})
    item.set_after({"branch_stock": current})
    item.set_payload({"branch_id": branch.id, "product_id": product.id, "adjustment": 0})
    db.session.add(item)
    db.session.flush()
    ok_validation = svc.validate_action_plan(plan.id)
    assert ok_validation["ok"] is True
    item.set_before({"branch_stock": current + 1})
    db.session.flush()
    failed_validation = svc.validate_action_plan(plan.id)
    assert failed_validation["ok"] is False
    db.session.rollback()
    print("action preflight ok")


def _assert_structured_helpers() -> None:
    text_value = svc._format_structured_ai_reply(
        {
            "answer": "تحليل مختصر",
            "key_points": ["نقطة"],
            "risks": ["خطر"],
            "next_steps": ["راجع الخطة"],
            "needs_admin_approval": True,
        }
    )
    assert "تحليل مختصر" in text_value
    assert "موافقة أدمن" in text_value
    assert svc._severity_reaches_threshold("warning", "critical") is False
    print("structured helpers ok")


if __name__ == "__main__":
    with app.app_context():
        _assert_excel_parser()
        _assert_order_detection()
        _assert_template_permissions()
        _assert_permissions_and_audit_plan()
        _assert_schedule_customization()
        _assert_action_preflight()
        _assert_structured_helpers()
    print("AI assistant smoke checks passed")
