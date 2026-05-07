-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy)
-- =============================================================================
-- Payment history fact table. Partitioned by payment_year and payment_month
-- for time-series queries typical in loan servicing (monthly reporting,
-- delinquency tracking, cash-flow analysis).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING,
    loan_account_id     BIGINT          NOT NULL,
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,
    type                STRING          NOT NULL,
    status              STRING          NOT NULL,
    received_date       DATE,
    processed_date      DATE,
    payment_year        INT             NOT NULL,
    payment_month       INT             NOT NULL,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment_year/payment_month for time-series reporting.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Foreign key constraint (informational in Databricks)
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id)
    REFERENCES loan_warehouse.loan_accounts (loan_account_id);

-- Z-ORDER recommendation:
-- OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id, payment_date);
