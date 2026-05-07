-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy)
-- =============================================================================
-- Payment transaction history table. Partitioned by payment_year for
-- time-range queries and efficient data lifecycle management.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id              BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_number  STRING,
    loan_account_number     STRING          NOT NULL,
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
COMMENT 'Payment history table migrated from legacy CDW_PMT_HIST. Partitioned by payment_year for time-range query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);
