"""FINORA CORE brain tables (Core DB, prefix ``fc_``). Created by migration v2 (modules/finora_core/migrations.py)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from extensions import db


class FcCustomer(db.Model):
    """A person/business talking to FINORA, independent of channel. Linked to a leads-CRM lead and a FINORA tenant."""

    __tablename__ = "fc_customers"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(150), nullable=False)
    lead_id = db.Column(db.Integer, index=True)  # business_leads.id (Core DB)
    tenant_slug = db.Column(db.String(100), index=True)  # FINORA account created for this customer
    lead_stage = db.Column(db.String(30), nullable=False, default="new", index=True)
    merged_into_id = db.Column(db.Integer, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FcCustomerIdentity(db.Model):
    """One identifier per row. (kind, value) is globally unique: the same Instagram id can never belong to two people."""

    __tablename__ = "fc_customer_identities"
    __table_args__ = (db.UniqueConstraint("kind", "value", name="uq_fc_identity_kind_value"),)

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)  # instagram_id | facebook_psid | phone | email | finora_tenant
    value = db.Column(db.String(200), nullable=False)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FcConversationCustomer(db.Model):
    """House-tenant conversation → customer."""

    __tablename__ = "fc_conversation_customers"

    conversation_ref = db.Column(db.String(40), primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FcMergeSuggestion(db.Model):
    """Two customers that may be the same person. Never merged automatically (spec §34)."""

    __tablename__ = "fc_merge_suggestions"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    candidate_id = db.Column(db.Integer, nullable=False, index=True)
    reason = db.Column(db.String(200), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(12), nullable=False, default="pending", index=True)
    # pending | merged | separate (a human said: different people) | dismissed | rejected (legacy) | unmerged
    evidence_json = db.Column(db.Text)  # [{"kind": "phone", "source": "message:12"}] — kinds only, never raw values
    merge_id = db.Column(db.Integer)  # fc_customer_merges.id once merged
    decided_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    decided_at = db.Column(db.DateTime)


class FcCustomerMerge(db.Model):
    """Ledger of one human-confirmed merge: exactly which rows moved, so the merge can be reverted (Phase 9)."""

    __tablename__ = "fc_customer_merges"

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, index=True)
    kept_id = db.Column(db.Integer, nullable=False, index=True)
    merged_id = db.Column(db.Integer, nullable=False, index=True)
    snapshot_json = db.Column(db.Text, nullable=False)  # moved row ids + previous scalar values
    status = db.Column(db.String(10), nullable=False, default="active")  # active | reverted
    actor = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reverted_by = db.Column(db.String(120))
    reverted_at = db.Column(db.DateTime)


class FcMemoryFact(db.Model):
    """Structured customer memory — an append-only evidence log per (customer, key).

    A changed value never overwrites: the old row becomes ``superseded`` (with ``superseded_at`` / ``superseded_by``),
    weaker contradicting evidence is kept as ``conflict``, an operator can ``retract`` a wrong fact, and evidence that
    was observed *before* the current fact (late delivery) is stored directly as history. Exactly one ``active`` row
    per key is the current fact."""

    __tablename__ = "fc_memory_facts"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False, index=True)
    value_json = db.Column(db.Text, nullable=False)
    value_normalized = db.Column(db.Text)  # canonical form used for comparisons (E.164, lowercase, folded Arabic)
    confidence = db.Column(db.Float, nullable=False)
    certainty = db.Column(db.String(12), nullable=False, default="stated")  # tentative | stated | verified
    source = db.Column(db.String(40), nullable=False)  # customer_message | ai_inference | human | channel | tool
    source_ref = db.Column(db.String(80))  # message id / tool call id / operator
    source_message_id = db.Column(db.String(80))  # house message the fact was read from (customer_message)
    status = db.Column(db.String(12), nullable=False, default="active", index=True)
    # active | superseded | conflict | retracted
    superseded_by = db.Column(db.Integer)
    status_reason = db.Column(db.String(200))
    changed_by = db.Column(db.String(120))  # operator who corrected / verified / retracted
    observed_at = db.Column(db.DateTime)  # when the evidence was produced (message time), not when it was stored
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    superseded_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def value(self) -> Any:
        return json.loads(self.value_json)


class FcKnowledgeDoc(db.Model):
    """Versioned FINORA product knowledge. Only ``published`` rows are ever used to answer customers."""

    __tablename__ = "fc_knowledge_docs"
    __table_args__ = (db.UniqueConstraint("doc_key", "version", name="uq_fc_knowledge_version"),)

    id = db.Column(db.Integer, primary_key=True)
    doc_key = db.Column(db.String(80), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(30), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(12), nullable=False, default="draft", index=True)
    # draft | in_review | published | retired — only ``published`` inside its effective window is customer-facing
    source = db.Column(db.String(200), nullable=False)  # verified FINORA source the text was taken from
    business_type = db.Column(db.String(40), index=True)  # None = every business type
    module = db.Column(db.String(60))
    feature = db.Column(db.String(80))
    supported_plans_json = db.Column(db.Text)  # ["basic", "pro"]; None/[] = every plan
    effective_from = db.Column(db.DateTime)
    effective_until = db.Column(db.DateTime)
    author = db.Column(db.String(120))
    revision_note = db.Column(db.String(300))
    reviewed_by = db.Column(db.String(120))
    published_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    published_at = db.Column(db.DateTime)


class FcKnowledgeEvent(db.Model):
    """Revision history of the knowledge base: every draft / review / publish / retire, with the global version."""

    __tablename__ = "fc_knowledge_events"

    id = db.Column(db.Integer, primary_key=True)
    doc_key = db.Column(db.String(80), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(20), nullable=False)  # draft | submit | publish | retire | reject
    actor = db.Column(db.String(120), nullable=False)
    note = db.Column(db.String(300))
    knowledge_version = db.Column(db.Integer, nullable=False)  # global knowledge-set version after this event
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FcAgentRun(db.Model):
    """One brain run for one inbound burst. No model reasoning is stored — only inputs refs, outcome and usage."""

    __tablename__ = "fc_agent_runs"

    id = db.Column(db.Integer, primary_key=True)
    conversation_ref = db.Column(db.String(40), nullable=False, index=True)
    customer_id = db.Column(db.Integer, index=True)
    trigger_message_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="running", index=True)
    # running | replied | waiting_approval | handed_off | skipped | failed | timeout
    outcome = db.Column(db.String(200))
    intents_json = db.Column(db.Text)
    prompt_version = db.Column(db.String(40), nullable=False)
    model = db.Column(db.String(80))
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    correlation_id = db.Column(db.String(64), nullable=False, index=True)
    # Phase 9 observability — operational trace only (never model reasoning), sensitive values redacted
    mode = db.Column(db.String(10), nullable=False, default="live")  # live | shadow
    knowledge_version = db.Column(db.Integer)
    confidence = db.Column(db.Float)  # top intent confidence
    latency_ms = db.Column(db.Integer)
    cost_usd = db.Column(db.Float)  # estimate from token usage; None when the model price is unknown
    trace_json = db.Column(db.Text)  # proposed actions, policy decisions, tools, verification, approvals
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    finished_at = db.Column(db.DateTime)


class FcToolCall(db.Model):
    """Every FINORA tool execution. ``idempotency_key`` makes repeated commands a no-op (spec §26)."""

    __tablename__ = "fc_tool_calls"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, index=True)
    approval_id = db.Column(db.Integer, index=True)
    tool = db.Column(db.String(40), nullable=False, index=True)
    risk = db.Column(db.String(10), nullable=False)
    risk_class = db.Column(db.String(20))  # READ_ONLY | LOW_RISK | MEDIUM_RISK | HIGH_RISK | NEVER_AUTOMATIC
    actor = db.Column(db.String(120), nullable=False)
    actor_type = db.Column(db.String(10), nullable=False)
    input_summary = db.Column(db.String(500))  # redacted
    status = db.Column(db.String(12), nullable=False, default="running")  # running | ok | failed | rejected
    result_json = db.Column(db.Text)  # redacted, never credentials
    verified = db.Column(db.Boolean)  # post-condition check of the tool's own verification function
    error = db.Column(db.String(500))
    idempotency_key = db.Column(db.String(120), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)


class FcApproval(db.Model):
    """Human approval for a restricted action. Executing happens only after an approver decides (spec §24)."""

    __tablename__ = "fc_approvals"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, index=True)
    conversation_ref = db.Column(db.String(40), index=True)
    run_id = db.Column(db.Integer)
    action = db.Column(db.String(40), nullable=False)
    args_json = db.Column(db.Text, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    old_value = db.Column(db.String(200))
    new_value = db.Column(db.String(200), nullable=False)
    agent_limit = db.Column(db.String(60))
    risk = db.Column(db.String(10), nullable=False)
    risk_class = db.Column(db.String(20))
    # Immutable action plan the operator approves (Phase 9). ``plan_hash`` = HMAC(server secret, canonical plan):
    # the decision must quote it, and execution uses exactly this plan — a changed plan needs a new approval.
    plan_json = db.Column(db.Text)
    plan_hash = db.Column(db.String(64))
    plan_version = db.Column(db.Integer, nullable=False, default=1)
    superseded_by_id = db.Column(db.Integer)
    status = db.Column(db.String(12), nullable=False, default="pending", index=True)
    # pending | approved | rejected | executed | failed | superseded
    decided_by = db.Column(db.String(120))
    decided_at = db.Column(db.DateTime)
    result_summary = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class FcOnboardingStep(db.Model):
    __tablename__ = "fc_onboarding_steps"
    __table_args__ = (db.UniqueConstraint("customer_id", "step", name="uq_fc_onboarding_step"),)

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    step = db.Column(db.String(30), nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False)
    evidence = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FcLeadTransition(db.Model):
    """Every lead-stage change is recorded (spec §14)."""

    __tablename__ = "fc_lead_transitions"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    from_stage = db.Column(db.String(30), nullable=False)
    to_stage = db.Column(db.String(30), nullable=False)
    actor = db.Column(db.String(120), nullable=False)
    actor_type = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FcShadowProposal(db.Model):
    """Shadow Mode (Phase 9): what FINORA CORE *would* have done for a customer message, stored next to what the
    human actually did. Nothing in a proposal is ever sent or executed."""

    __tablename__ = "fc_shadow_proposals"
    __table_args__ = (db.UniqueConstraint("trigger_ref", name="uq_fc_shadow_trigger"),)

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, index=True)
    conversation_ref = db.Column(db.String(40), nullable=False, index=True)
    customer_id = db.Column(db.Integer, index=True)
    trigger_message_id = db.Column(db.Integer, nullable=False)
    trigger_ref = db.Column(db.String(120), nullable=False)  # house-scoped message ref (dedupe per burst)
    proposed_reply = db.Column(db.Text, nullable=False)
    plan_json = db.Column(db.Text, nullable=False)  # intents, actions + policy verdicts, approvals it would request
    confidence = db.Column(db.Float)
    proposed_escalation = db.Column(db.Boolean, nullable=False, default=False)
    escalation_reason = db.Column(db.String(300))
    status = db.Column(db.String(12), nullable=False, default="pending", index=True)
    # pending | answered | superseded (a newer customer message arrived first)
    human_message_id = db.Column(db.Integer)
    human_reply = db.Column(db.Text)
    human_actor = db.Column(db.String(120))
    human_replied_at = db.Column(db.DateTime)
    operator_used = db.Column(db.Boolean)  # the operator started from the proposal
    accepted = db.Column(db.Boolean)  # sent unchanged
    edited = db.Column(db.Boolean)  # started from the proposal and changed it
    similarity = db.Column(db.Float)  # 0..1 proposal vs human reply
    escalation_decision = db.Column(db.String(12))  # agree | disagree (operator review of the escalation call)
    reviewed_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


BRAIN_TABLES = [
    FcCustomer.__table__,
    FcCustomerIdentity.__table__,
    FcConversationCustomer.__table__,
    FcMergeSuggestion.__table__,
    FcMemoryFact.__table__,
    FcKnowledgeDoc.__table__,
    FcAgentRun.__table__,
    FcToolCall.__table__,
    FcApproval.__table__,
    FcOnboardingStep.__table__,
    FcLeadTransition.__table__,
]

# Phase 9 (migration v3): new tables + columns added to the v2 tables.
V3_TABLES = [
    FcCustomerMerge.__table__,
    FcKnowledgeEvent.__table__,
    FcShadowProposal.__table__,
]
V3_COLUMNS: dict[str, list[str]] = {
    "fc_merge_suggestions": ["evidence_json", "merge_id"],
    "fc_memory_facts": ["value_normalized", "certainty", "source_message_id", "status_reason", "changed_by",
                        "observed_at", "superseded_at"],
    "fc_knowledge_docs": ["business_type", "module", "feature", "supported_plans_json", "effective_from",
                          "effective_until", "author", "revision_note", "reviewed_by"],
    "fc_agent_runs": ["mode", "knowledge_version", "confidence", "latency_ms", "cost_usd", "trace_json"],
    "fc_tool_calls": ["risk_class", "verified"],
    "fc_approvals": ["risk_class", "plan_json", "plan_hash", "plan_version", "superseded_by_id"],
}
