-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year/month for
-- efficient time-range queries on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id              BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_payment_seq      STRING,
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
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP,
    payment_year            INT             NOT NULL,
    payment_month           INT             NOT NULL,
    _migration_source       STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at            TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment_year and payment_month for time-range queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_type_valid EXPECT (type IN ('REGULAR', 'EXTRA', 'PARTIAL', 'PREPAYMENT'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_status_valid EXPECT (status IN ('POSTED', 'REVERSED', 'NSF', 'PENDING'));

ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_amount_positive EXPECT (total_amount > 0);
