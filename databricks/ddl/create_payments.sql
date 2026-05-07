-- =============================================================================
-- Delta Lake: payments table
-- Source: CDW_PMT_HIST (legacy)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING          COMMENT 'Legacy PMT_SEQ_NBR for audit trail',
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK to loan_accounts.id',
    payment_date        DATE            NOT NULL COMMENT 'Parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10,2)   NOT NULL,
    principal_amount    DECIMAL(10,2)   NOT NULL,
    interest_amount     DECIMAL(10,2)   NOT NULL,
    escrow_amount       DECIMAL(10,2)   DEFAULT 0.00,
    late_fee            DECIMAL(10,2)   DEFAULT 0.00,
    type                STRING          NOT NULL COMMENT 'REGULAR/EXTRA/PARTIAL/PREPAYMENT',
    status              STRING          NOT NULL COMMENT 'POSTED/REVERSED/NSF/PENDING',
    received_date       DATE,
    processed_date      DATE,
    reconciled          BOOLEAN         DEFAULT true COMMENT 'False if component sum != total',
    component_sum       DECIMAL(10,2)   COMMENT 'Computed: principal+interest+escrow+late_fee',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    CONSTRAINT payments_pk PRIMARY KEY (id),
    CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Payment history migrated from CDW_PMT_HIST. Includes reconciliation flag for audit.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

CREATE INDEX IF NOT EXISTS idx_payments_loan_account
ON loan_warehouse.payments (loan_account_id);

CREATE INDEX IF NOT EXISTS idx_payments_date
ON loan_warehouse.payments (payment_date);
