"""Import and dedup acceptance test — أزياء الملك scenario (spec §99)."""
import io

import pandas as pd

from tests.leads_crm_helpers import get_leads_test_app, unique_phone


def test_import_exact_duplicate_merge():
    app = get_leads_test_app()
    from flask import g, session

    with app.app_context():
        g.tenant = None

        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults
        from models.core.leads.models import BusinessActivity, BusinessLead, LeadInteraction
        from services.leads_crm.lead_service import create_lead
        from services.leads_crm.interaction_service import add_interaction
        from services.leads_crm.import_service import (
            create_batch_from_upload,
            apply_mapping,
            normalize_and_validate_batch,
            detect_duplicates_in_batch,
            commit_batch,
        )

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()

        activity = BusinessActivity.query.filter_by(slug="clothing").first()

        phone = unique_phone()

        # Existing lead
        lead, _ = create_lead({
            "business_name": "أزياء الملك",
            "activity_id": activity.id,
            "phone": phone,
            "governorate": "بغداد",
            "district": "المنصور",
            "status": "INTERESTED",
            "source_primary": "manual",
        }, allow_possible_duplicate=True)
        assert lead is not None
        add_interaction(lead.id, "CALL", note="اتصال سابق")
        lead_id = lead.id
        interaction_count_before = LeadInteraction.query.filter_by(lead_id=lead_id).count()

        # Excel import with same phone
        df = pd.DataFrame([{
            "اسم المحل": "ازياء الملك",
            "الهاتف": f"+964{phone[1:]}",
            "العنوان": "المنصور - شارع الرواد",
            "Instagram": "@kingfashion",
        }])
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        buf.seek(0)

        batch = create_batch_from_upload(buf.read(), "test.xlsx", activity_id=activity.id, source_label="excel_import")
        apply_mapping(batch.id, {
            "business_name": "اسم المحل",
            "phone": "الهاتف",
            "full_address": "العنوان",
            "instagram_url": "Instagram",
            "governorate": "",
        })
        normalize_and_validate_batch(batch.id)
        dedup = detect_duplicates_in_batch(batch.id)
        assert dedup["stats"]["exact"] >= 1

        result = commit_batch(batch.id, merge_exact=True)
        assert result["results"]["merged"] >= 1
        assert result["results"]["created"] == 0

        merged = BusinessLead.query.get(lead_id)
        assert merged.status == "INTERESTED"
        assert merged.full_address == "المنصور - شارع الرواد"
        assert merged.instagram_url == "@kingfashion"
        assert LeadInteraction.query.filter_by(lead_id=lead_id).count() == interaction_count_before

        total_active = BusinessLead.query.filter(
            BusinessLead.deleted_at.is_(None),
            BusinessLead.merged_into_lead_id.is_(None),
            BusinessLead.normalized_business_name.contains("ازياء"),
        ).count()
        assert total_active >= 1
