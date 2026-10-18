-- FINORA Clinics accounting bridge (PostgreSQL tenant databases).
-- Additive and repeatable: no operational data is posted by this migration.

CREATE TABLE IF NOT EXISTS accounting_posting (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    branch_id INTEGER,
    source_module VARCHAR(40) NOT NULL DEFAULT 'clinics',
    source_type VARCHAR(80) NOT NULL,
    source_id INTEGER NOT NULL,
    source_event VARCHAR(80) NOT NULL,
    journal_entry_id INTEGER REFERENCES journal_entry(id),
    status VARCHAR(20) NOT NULL DEFAULT 'unposted',
    posted_at TIMESTAMP,
    posted_by INTEGER,
    reversed_at TIMESTAMP,
    reversal_journal_entry_id INTEGER REFERENCES journal_entry(id),
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_accounting_posting_status
        CHECK (status IN ('unposted', 'posted', 'reversed', 'error')),
    CONSTRAINT uq_accounting_posting_source_event
        UNIQUE (tenant_id, source_module, source_type, source_id, source_event)
);

CREATE INDEX IF NOT EXISTS ix_accounting_posting_source
    ON accounting_posting (tenant_id, source_module, source_type, source_id);
CREATE INDEX IF NOT EXISTS ix_accounting_posting_status
    ON accounting_posting (tenant_id, status);

ALTER TABLE clinic_doctor_settlement
    ADD COLUMN IF NOT EXISTS payment_method VARCHAR(40) NOT NULL DEFAULT 'cash';

ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS cash_collections INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS cash_refunds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS cash_expenses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS supplier_payments INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS doctor_payments INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS other_cash_in INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS other_cash_out INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinic_cash_session ADD COLUMN IF NOT EXISTS difference INTEGER;

