"""Onboarding checklist (spec §27) derived from evidence (memory, tools, tenant data) — never from model claims."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from sqlalchemy.orm import Session

from . import memory
from .models import FcCustomer, FcOnboardingStep

STEPS = [
    ("info", "إكمال معلومات العميل"),
    ("offer", "إرسال عرض مناسب"),
    ("trial", "إنشاء الحساب"),
    ("setup", "تهيئة النظام"),
    ("training", "تدريب على الاستخدام"),
    ("activation", "بدء الاستخدام الفعلي"),
]
_ACTIVITY_TABLES = ("clinic_patients", "clinic_appointments", "invoice", "customer", "product", "orders")


def _tenant_has_activity(slug: str) -> bool:
    """Real usage = the customer created business data in their own tenant (read-only, parameter-free queries)."""
    from extensions_tenant import get_tenant_db_path

    path = get_tenant_db_path(slug)
    if not os.path.exists(path):
        return False
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in _ACTIVITY_TABLES:
            if table in tables and conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():  # noqa: S608 (fixed names)
                return True
        return False
    finally:
        conn.close()


def refresh(s: Session, customer: FcCustomer, *, training_given: bool = False) -> list[dict[str, Any]]:
    facts = memory.active_facts(s, customer.id)
    evidence = {
        "info": ("businessType" in facts and not memory.qualification_missing(facts), "profile complete"),
        "offer": ("recommendedPlan" in facts, "plan recommended"),
        "trial": (bool(customer.tenant_slug), customer.tenant_slug or ""),
        "setup": (bool(customer.tenant_slug), "business type configured at provisioning"),
        "training": (training_given, "training answer delivered"),
        "activation": (bool(customer.tenant_slug) and _tenant_has_activity(customer.tenant_slug), "tenant has business data"),
    }
    rows = {r.step: r for r in s.query(FcOnboardingStep).filter_by(customer_id=customer.id).all()}
    out = []
    for key, label in STEPS:
        done, why = evidence[key]
        row = rows.get(key)
        if row is None:
            row = FcOnboardingStep(customer_id=customer.id, step=key, done=False)
            s.add(row)
        if done and not row.done:  # steps only move forward
            row.done, row.evidence = True, why[:200]
        out.append({"key": key, "label": label, "done": row.done})
    s.flush()
    return out
