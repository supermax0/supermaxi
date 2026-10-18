"""Leads CRM core database models (Super Admin Core DB)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class BusinessActivity(db.Model):
    __tablename__ = "business_activities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_ar = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    icon = db.Column(db.String(60), default="fa-store")
    color = db.Column(db.String(20), default="#6366f1")
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    leads = db.relationship("BusinessLead", back_populates="activity", lazy="dynamic")


class LeadStatusConfig(db.Model):
    __tablename__ = "lead_status_configs"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    label_ar = db.Column(db.String(80), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    color = db.Column(db.String(20), default="#6366f1")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_pipeline = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BusinessLead(db.Model):
    __tablename__ = "business_leads"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("business_activities.id"), nullable=False, index=True)

    business_name = db.Column(db.String(255), nullable=False)
    normalized_business_name = db.Column(db.String(255), nullable=False, index=True)
    owner_name = db.Column(db.String(120), nullable=True)

    governorate = db.Column(db.String(80), nullable=True, index=True)
    city = db.Column(db.String(80), nullable=True)
    district = db.Column(db.String(120), nullable=True)
    area = db.Column(db.String(120), nullable=True)
    full_address = db.Column(db.Text, nullable=True)

    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    website = db.Column(db.String(255), nullable=True)
    instagram_url = db.Column(db.String(255), nullable=True)
    facebook_url = db.Column(db.String(255), nullable=True)
    tiktok_url = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(40), default="NEW", nullable=False, index=True)
    priority = db.Column(db.String(20), default="MEDIUM", nullable=False)

    assigned_to_superadmin_id = db.Column(db.Integer, db.ForeignKey("super_admins.id"), nullable=True, index=True)

    preferred_contact_method = db.Column(db.String(40), nullable=True)
    last_contact_at = db.Column(db.DateTime, nullable=True)
    next_follow_up_at = db.Column(db.DateTime, nullable=True, index=True)

    trial_started_at = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True, index=True)

    finora_company_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=True, index=True)

    estimated_value = db.Column(db.Numeric(12, 2), nullable=True)
    monthly_subscription_value = db.Column(db.Numeric(12, 2), nullable=True)

    source_primary = db.Column(db.String(120), nullable=True, index=True)
    lead_score = db.Column(db.Integer, default=0, nullable=False)

    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    duplicate_status = db.Column(db.String(20), default="NONE", nullable=False, index=True)

    merged_into_lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=True, index=True)
    merged_at = db.Column(db.DateTime, nullable=True)
    merged_by = db.Column(db.Integer, nullable=True)

    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    activity = db.relationship("BusinessActivity", back_populates="leads")
    phones = db.relationship(
        "BusinessLeadPhone",
        back_populates="lead",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    sources = db.relationship(
        "LeadSourceRecord",
        back_populates="lead",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    notes = db.relationship(
        "LeadNote",
        back_populates="lead",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    interactions = db.relationship(
        "LeadInteraction",
        back_populates="lead",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    follow_ups = db.relationship(
        "LeadFollowUp",
        back_populates="lead",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def primary_phone(self):
        for p in self.phones:
            if p.is_primary:
                return p
        return self.phones[0] if self.phones else None


class BusinessLeadPhone(db.Model):
    __tablename__ = "business_lead_phones"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)

    phone_original = db.Column(db.String(40), nullable=False)
    normalized_phone = db.Column(db.String(20), nullable=False, unique=True, index=True)
    country_code = db.Column(db.String(5), default="964")

    is_primary = db.Column(db.Boolean, default=True, nullable=False)
    is_whatsapp = db.Column(db.Boolean, default=False, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_valid = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead = db.relationship("BusinessLead", back_populates="phones")


class LeadSourceRecord(db.Model):
    __tablename__ = "lead_source_records"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    source_name = db.Column(db.String(120), nullable=False)
    source_detail = db.Column(db.String(255), nullable=True)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("lead_import_batches.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship("BusinessLead", back_populates="sources")


class LeadNote(db.Model):
    __tablename__ = "lead_notes"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    author_superadmin_id = db.Column(db.Integer, nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship("BusinessLead", back_populates="notes")


class LeadInteraction(db.Model):
    __tablename__ = "lead_interactions"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    superadmin_id = db.Column(db.Integer, nullable=True)

    interaction_type = db.Column(db.String(30), nullable=False)
    result_status = db.Column(db.String(40), nullable=True)
    note = db.Column(db.Text, nullable=True)

    contacted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    next_follow_up_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship("BusinessLead", back_populates="interactions")


class LeadFollowUp(db.Model):
    __tablename__ = "lead_follow_ups"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    superadmin_id = db.Column(db.Integer, nullable=True)

    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending | done | postponed
    completed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship("BusinessLead", back_populates="follow_ups")


class LeadSavedView(db.Model):
    __tablename__ = "lead_saved_views"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    superadmin_id = db.Column(db.Integer, nullable=True)
    filters_json = db.Column(db.Text, nullable=False, default="{}")
    is_shared = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LeadImportBatch(db.Model):
    __tablename__ = "lead_import_batches"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("business_activities.id"), nullable=True)
    source_label = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(30), default="uploaded", nullable=False)
    mapping_json = db.Column(db.Text, nullable=True)
    stats_json = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rows = db.relationship("LeadImportRow", back_populates="batch", lazy="dynamic", cascade="all, delete-orphan")


class LeadImportRow(db.Model):
    __tablename__ = "lead_import_rows"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("lead_import_batches.id"), nullable=False, index=True)
    row_number = db.Column(db.Integer, nullable=False)
    raw_json = db.Column(db.Text, nullable=False)
    normalized_json = db.Column(db.Text, nullable=True)
    validation_errors = db.Column(db.Text, nullable=True)
    duplicate_level = db.Column(db.String(20), nullable=True)
    duplicate_lead_id = db.Column(db.Integer, nullable=True)
    duplicate_score = db.Column(db.Float, nullable=True)
    duplicate_reason = db.Column(db.Text, nullable=True)
    commit_action = db.Column(db.String(30), nullable=True)  # create | skip | merge | review
    result_lead_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    batch = db.relationship("LeadImportBatch", back_populates="rows")


class LeadDuplicateCandidate(db.Model):
    __tablename__ = "lead_duplicate_candidates"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    candidate_lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    duplicate_level = db.Column(db.String(20), nullable=False)
    duplicate_score = db.Column(db.Float, nullable=False)
    duplicate_reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending | merged | dismissed
    reviewed_by = db.Column(db.Integer, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LeadMergeLog(db.Model):
    __tablename__ = "lead_merge_logs"

    id = db.Column(db.Integer, primary_key=True)
    target_lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    source_lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, index=True)
    merged_by = db.Column(db.Integer, nullable=True)
    snapshot_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LeadAuditLog(db.Model):
    __tablename__ = "lead_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=True, index=True)
    action = db.Column(db.String(60), nullable=False)
    actor_superadmin_id = db.Column(db.Integer, nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class LeadScore(db.Model):
    __tablename__ = "lead_scores"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("business_leads.id"), nullable=False, unique=True, index=True)
    score = db.Column(db.Integer, default=0, nullable=False)
    factors_json = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LeadAutomationRule(db.Model):
    __tablename__ = "lead_automation_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    trigger_event = db.Column(db.String(60), nullable=False)
    conditions_json = db.Column(db.Text, nullable=True)
    actions_json = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LeadDiscoveryRun(db.Model):
    __tablename__ = "lead_discovery_runs"

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(30), default="running", nullable=False, index=True)
    source_name = db.Column(db.String(120), default="OpenStreetMap", nullable=False)
    requested_limit = db.Column(db.Integer, default=100, nullable=False)
    discovered_count = db.Column(db.Integer, default=0, nullable=False)
    created_count = db.Column(db.Integer, default=0, nullable=False)
    skipped_count = db.Column(db.Integer, default=0, nullable=False)
    duplicate_count = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    settings_json = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
