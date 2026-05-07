-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Payment transaction fact table. High-volume, append-heavy.
-- Partitioned by payment_date (year-month extracted) for time-range queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING,
    loan_account_id     BIGINT NOT NULL,
    payment_date        DATE NOT NULL,
    total_amount        DECIMAL(10, 2) NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2) DEFAULT 0,
    type                STRING NOT NULL,
    status              STRING NOT NULL,
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP DEFAULT current_timestamp(),
    updated_at          TIMESTAMP DEFAULT current_timestamp(),
    -- Partition column derived from payment_date
    payment_year_month  STRING GENERATED ALWAYS AS (date_format(payment_date, 'yyyy-MM')),

    CONSTRAINT payments_pk PRIMARY KEY (id),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id),
    CONSTRAINT payments_type_values CHECK (type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT')),
    CONSTRAINT payments_status_values CHECK (status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING')),
    CONSTRAINT payments_total_pos CHECK (total_amount >= 0)
)
USING DELTA
PARTITIONED BY (payment_year_month)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by year-month for efficient time-range queries. FK to loan_accounts.';
