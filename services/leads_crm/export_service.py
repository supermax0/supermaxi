"""Export Leads to Excel."""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from services.leads_crm.lead_service import list_leads
from utils.leads_crm.phone_normalize import phone_display


def export_leads_excel(**filters: Any) -> bytes:
    data = list_leads(page=1, per_page=10000, **filters)
    rows = []
    for item in data["leads"]:
        rows.append({
            "business_name": item["business_name"],
            "activity": item["activity_name"],
            "phone": item["primary_phone"],
            "governorate": item["governorate"],
            "city": item["city"],
            "district": item["district"],
            "full_address": item["full_address"],
            "status": item["status"],
            "priority": item["priority"],
            "source": item["source_primary"],
            "instagram": item["instagram_url"],
            "score": item["lead_score"],
            "created_at": item["created_at"],
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Leads")
    buf.seek(0)
    return buf.read()
