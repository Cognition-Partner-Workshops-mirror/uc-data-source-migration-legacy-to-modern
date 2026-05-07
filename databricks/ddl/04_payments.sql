-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment history fact table. Partitioned by payment year/month for
-- time-series queries and efficient pruning of historical data.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING,
    loan_account_id     BIGINT NOT NULL,
    payment_date        DATE NOT NULL,
    total_amount        DECIMAL(10, 2),
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
    _ingestion_ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    _source_system      STRING DEFAULT 'CDW_PMT_HIST'
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
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by year/month for time-series analysis.';

-- Constraints
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_pk PRIMARY KEY (id);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_loan_account_fk
    FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts (id);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_amount_nonneg
    CHECK (total_amount IS NULL OR total_amount >= 0);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_type_valid
    CHECK (type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_status_valid
    CHECK (status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING'));
