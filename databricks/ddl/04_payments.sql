-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year/month
-- for time-series query optimization on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING,
    loan_account_number STRING          NOT NULL,
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
    payment_year        INT             GENERATED ALWAYS AS (year(payment_date)),
    payment_month       INT             GENERATED ALWAYS AS (month(payment_date)),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment year/month.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_amount_positive EXPECT (total_amount >= 0);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_type_valid
    EXPECT (type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_status_valid
    EXPECT (status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_principal_non_negative
    EXPECT (principal_amount IS NULL OR principal_amount >= 0);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_interest_non_negative
    EXPECT (interest_amount IS NULL OR interest_amount >= 0);
