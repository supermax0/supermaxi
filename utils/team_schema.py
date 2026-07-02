"""Schema helpers for team admin pages (employees, agents)."""

from __future__ import annotations

from sqlalchemy import inspect, text

from extensions import db
from utils.employee_commission import get_fixed_employee_commission_percent


def _resolve_engine():
    from flask import g

    if getattr(g, "tenant", None):
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(g.tenant)
    return db.engine


def ensure_delivery_agent_schema() -> None:
    """Add delivery_agent columns expected by the ORM (safe to call each request)."""
    try:
        engine = _resolve_engine()
        inspector = inspect(engine)
        if "delivery_agent" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("delivery_agent")}
        dialect = engine.dialect.name
        bool_default = "TRUE" if dialect == "postgresql" else "1"

        with engine.connect() as conn:
            changed = False
            if "username" not in columns:
                conn.execute(text("ALTER TABLE delivery_agent ADD COLUMN username VARCHAR(50)"))
                changed = True
            if "password" not in columns:
                conn.execute(text("ALTER TABLE delivery_agent ADD COLUMN password VARCHAR(200)"))
                changed = True
            if "is_active" not in columns:
                conn.execute(
                    text(f"ALTER TABLE delivery_agent ADD COLUMN is_active BOOLEAN DEFAULT {bool_default}")
                )
                changed = True
            if "salary" not in columns:
                conn.execute(text("ALTER TABLE delivery_agent ADD COLUMN salary INTEGER DEFAULT 0"))
                changed = True
            if "employee_id" not in columns:
                conn.execute(text("ALTER TABLE delivery_agent ADD COLUMN employee_id INTEGER"))
                changed = True
            if changed:
                conn.commit()
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" not in msg and "already exists" not in msg:
            print(f"[team_schema] delivery_agent ensure failed: {e}")


def build_employees_grid_rows(employees_list, stats_map, delivery_agents, agent_stats_map):
    """Serialize employee + delivery-agent rows for the AG Grid script."""
    rows = []
    for e in employees_list:
        s = stats_map.get(e.id, {"orders": 0, "sales": 0})
        sales = int(s.get("sales") or 0)
        orders = int(s.get("orders") or 0)
        fixed_commission = get_fixed_employee_commission_percent()
        commission_value = int(sales * fixed_commission / 100)
        try:
            role_labels = [r.name for r in (e.roles or [])]
        except Exception:
            role_labels = []
        try:
            pages_count = e.pages.count()
        except Exception:
            pages_count = 0
        rows.append(
            {
                "id": e.id,
                "grid_id": f"emp-{e.id}",
                "name": e.name,
                "username": e.username,
                "role": e.role,
                "role_name": "كاشير" if e.role == "cashier" else "مدير",
                "role_labels": role_labels,
                "pages_count": pages_count,
                "status": "active" if e.is_active else "inactive",
                "orders": orders,
                "sales": sales,
                "salary": int(e.salary or 0),
                "commission": fixed_commission,
                "total_due": int(e.salary or 0) + commission_value,
                "is_delivery": False,
            }
        )

    for agent in delivery_agents:
        if not agent.username:
            continue
        s = agent_stats_map.get(agent.id, {"orders": 0, "sales": 0})
        agent_salary = int(getattr(agent, "salary", 0) or 0)
        rows.append(
            {
                "id": agent.id,
                "grid_id": f"agent-{agent.id}",
                "name": f"🚚 {agent.name}",
                "username": agent.username,
                "role": "delivery",
                "role_name": "مندوب توصيل",
                "role_labels": [],
                "pages_count": 0,
                "status": "active" if agent.is_active else "inactive",
                "orders": int(s.get("orders") or 0),
                "sales": int(s.get("sales") or 0),
                "salary": agent_salary,
                "commission": 0,
                "total_due": agent_salary,
                "is_delivery": True,
            }
        )
    return rows
