-- =============================================================================
-- Delta Lake Table: payments (fact table)
-- Source: CDW_PMT_HIST
-- =============================================================================
-- Payment history fact table. Partitioned by payment year/month for efficient
-- time-range queries on payment activity.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING,
    loan_account_number STRING NOT NULL,
    payment_date        DATE NOT NULL,
    total_amount        DECIMAL(10, 2) NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2),
    type                STRING,
    status              STRING NOT NULL,
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT GENERATED ALWAYS AS (YEAR(payment_date)),
    payment_month       INT GENERATED ALWAYS AS (MONTH(payment_date)),
    _ingestion_ts       TIMESTAMP DEFAULT current_timestamp(),
    _source_system      STRING DEFAULT 'CDW_LEGACY'
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment_year and payment_month for time-range analytics.';

-- Constraints
ALTER TABLE loan_warehouse.payments
ADD CONSTRAINT payments_status_check CHECK (
    status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING')
);

ALTER TABLE loan_warehouse.payments
ADD CONSTRAINT payments_type_check CHECK (
    type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT')
);

ALTER TABLE loan_warehouse.payments
ADD CONSTRAINT payments_amount_positive CHECK (
    total_amount >= 0
);
