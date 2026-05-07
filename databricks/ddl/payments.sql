-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy CDW Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year/month to
-- support monthly reporting, reconciliation, and efficient time-range scans.
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
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT             GENERATED ALWAYS AS (YEAR(payment_date)),
    payment_month       INT             GENERATED ALWAYS AS (MONTH(payment_date)),
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year and month for monthly reporting and reconciliation.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
