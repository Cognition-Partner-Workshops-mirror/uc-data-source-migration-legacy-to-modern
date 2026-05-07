-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy)
-- =============================================================================
-- Payment history fact table. Partitioned by payment year/month for efficient
-- time-range queries which are the dominant access pattern for payment data.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key         BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING,
    loan_account_key    BIGINT          NOT NULL,
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
    payment_year        INT GENERATED ALWAYS AS (YEAR(payment_date)),
    payment_month       INT GENERATED ALWAYS AS (MONTH(payment_date)),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_type_values
    CHECK (type IN ('Regular', 'Extra', 'Partial', 'Prepayment'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_status_values
    CHECK (status IN ('Posted', 'Reversed', 'NSF', 'Pending'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_positive_amount
    CHECK (total_amount > 0);
