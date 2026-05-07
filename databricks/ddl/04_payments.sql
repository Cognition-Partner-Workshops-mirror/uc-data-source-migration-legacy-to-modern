-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy CDW)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year/month for
-- time-series queries and efficient pruning of historical data.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key         BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING,
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
    payment_year        INT GENERATED ALWAYS AS (YEAR(payment_date)),
    payment_month       INT GENERATED ALWAYS AS (MONTH(payment_date)),
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST'
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year and month for time-series analytics.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);

-- Constraints
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_type_valid
    CHECK (type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_status_valid
    CHECK (status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_amount_positive
    CHECK (total_amount > 0);
