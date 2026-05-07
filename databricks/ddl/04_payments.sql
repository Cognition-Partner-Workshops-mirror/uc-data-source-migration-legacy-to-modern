-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy)
-- =============================================================================
-- Payment history fact table. Partitioned by payment year/month for
-- time-range queries common in loan servicing and reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key             BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id       STRING,
    loan_account_number     STRING NOT NULL,
    payment_date            DATE NOT NULL,
    total_amount            DECIMAL(10, 2) NOT NULL,
    principal_amount        DECIMAL(10, 2),
    interest_amount         DECIMAL(10, 2),
    escrow_amount           DECIMAL(10, 2),
    late_fee                DECIMAL(10, 2) DEFAULT 0,
    type                    STRING NOT NULL,
    status                  STRING NOT NULL,
    received_date           DATE,
    processed_date          DATE,
    payment_year            INT,
    payment_month           INT,
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP,
    _load_timestamp         TIMESTAMP DEFAULT current_timestamp(),
    _source_system          STRING DEFAULT 'CDW_PMT_HIST'
)
USING DELTA
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST'
PARTITIONED BY (payment_year, payment_month)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);
