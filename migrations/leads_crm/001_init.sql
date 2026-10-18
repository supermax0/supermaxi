-- Leads CRM initial schema (reference migration for Core DB)
-- Applied via SQLAlchemy create_all + ensure_leads_crm_schema()

-- Tables: business_activities, lead_status_configs, business_leads,
-- business_lead_phones, lead_source_records, lead_notes, lead_interactions,
-- lead_follow_ups, lead_saved_views, lead_import_batches, lead_import_rows,
-- lead_duplicate_candidates, lead_merge_logs, lead_audit_logs,
-- lead_scores, lead_automation_rules

-- Unique constraint on business_lead_phones.normalized_phone enforced at ORM level.
