-- Daily Purchase List: additive tenant-safe migration.
-- Existing tenant databases also receive this schema through
-- utils.purchase_list_schema.ensure_purchase_list_schema().
CREATE TABLE IF NOT EXISTS purchase_list (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenant(id),
    branch_id INTEGER NOT NULL REFERENCES branch(id),
    warehouse_id INTEGER REFERENCES warehouse(id),
    list_number VARCHAR(60) NOT NULL,
    list_date DATE NOT NULL,
    responsible_employee_id INTEGER REFERENCES employee(id),
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_by INTEGER REFERENCES employee(id),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    executed_by INTEGER REFERENCES employee(id),
    executed_at DATETIME,
    execution_key VARCHAR(100),
    CONSTRAINT uq_purchase_list_tenant_number UNIQUE (tenant_id, list_number),
    CONSTRAINT uq_purchase_list_execution_key UNIQUE (execution_key),
    CONSTRAINT ck_purchase_list_status CHECK (status IN ('draft','open','partially_executed','executing','executed','cancelled'))
);

CREATE TABLE IF NOT EXISTS purchase_list_item (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenant(id),
    purchase_list_id INTEGER NOT NULL REFERENCES purchase_list(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES product(id),
    supplier_id INTEGER NOT NULL REFERENCES supplier(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_id INTEGER,
    unit_name VARCHAR(50) DEFAULT 'قطعة',
    purchase_price INTEGER NOT NULL DEFAULT 0,
    discount INTEGER NOT NULL DEFAULT 0,
    tax INTEGER NOT NULL DEFAULT 0,
    payment_method VARCHAR(30) NOT NULL DEFAULT 'credit',
    payment_account_id INTEGER REFERENCES treasury_account(id),
    purchase_reason VARCHAR(40),
    notes TEXT,
    is_selected BOOLEAN NOT NULL DEFAULT 1,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    purchase_invoice_id INTEGER REFERENCES purchase(id),
    created_by INTEGER REFERENCES employee(id),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    executed_at DATETIME,
    CONSTRAINT ck_purchase_list_item_quantity CHECK (quantity > 0),
    CONSTRAINT ck_purchase_list_item_amounts CHECK (purchase_price >= 0 AND discount >= 0 AND tax >= 0),
    CONSTRAINT ck_purchase_list_item_payment_method CHECK (payment_method IN ('cash','card','bank_transfer','credit')),
    CONSTRAINT ck_purchase_list_item_status CHECK (status IN ('draft','selected','executed','discarded','cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_purchase_list_tenant_status ON purchase_list (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_purchase_list_branch_date ON purchase_list (branch_id, list_date);
CREATE INDEX IF NOT EXISTS ix_purchase_list_item_list_status ON purchase_list_item (purchase_list_id, status);
CREATE INDEX IF NOT EXISTS ix_purchase_list_item_supplier ON purchase_list_item (supplier_id);
CREATE INDEX IF NOT EXISTS ix_purchase_list_item_product ON purchase_list_item (product_id);
CREATE INDEX IF NOT EXISTS ix_purchase_list_item_invoice ON purchase_list_item (purchase_invoice_id);
