-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.payments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING,
    loan_account_id     BIGINT NOT NULL,
    payment_date        DATE NOT NULL,
    total_amount        DECIMAL(10, 2) NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2) DEFAULT 0.00,
    type                STRING NOT NULL,
    status              STRING NOT NULL,
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_management.loan_accounts(id)
)
USING DELTA
COMMENT 'Payment history table migrated from CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
PARTITIONED BY (status);
