-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. High-volume table partitioned by payment year
-- for time-range query efficiency and data lifecycle management.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key             BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id       STRING,
    loan_account_key        BIGINT          NOT NULL,
    payment_date            DATE            NOT NULL,
    total_amount            DECIMAL(10, 2)  NOT NULL,
    principal_amount        DECIMAL(10, 2),
    interest_amount         DECIMAL(10, 2),
    escrow_amount           DECIMAL(10, 2),
    late_fee                DECIMAL(10, 2)  DEFAULT 0,
    type                    STRING          NOT NULL,
    status                  STRING          NOT NULL,
    received_date           DATE,
    processed_date          DATE,
    payment_year            INT,
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP,
    _ingestion_ts           TIMESTAMP       DEFAULT current_timestamp(),
    _source_system          STRING          DEFAULT 'CDW_PMT_HIST'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite'       = 'true',
    'delta.autoOptimize.autoCompact'         = 'true',
    'quality.constraints.loan_account_key'   = 'loan_account_key IS NOT NULL',
    'quality.constraints.payment_date'       = 'payment_date IS NOT NULL',
    'quality.constraints.total_amount'       = 'total_amount IS NOT NULL'
);

ALTER TABLE loan_warehouse.payments
    SET TBLPROPERTIES ('delta.dataSkippingNumIndexedCols' = '8');
