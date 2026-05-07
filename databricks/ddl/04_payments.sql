-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year and status for
-- time-range and reconciliation queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING          COMMENT 'Original PMT_SEQ_NBR from CDW_PMT_HIST',
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.loan_account_id',
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,
    type                STRING          NOT NULL    COMMENT 'REGULAR, EXTRA, PARTIAL, PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'POSTED, REVERSED, NSF, PENDING',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT             COMMENT 'Derived partition column from payment_date',
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST'
PARTITIONED BY (payment_year, status)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.expectation.loan_account_id' = 'loan_account_id IS NOT NULL',
    'quality.expectation.payment_date'    = 'payment_date IS NOT NULL',
    'quality.expectation.total_amount'    = 'total_amount IS NOT NULL'
);

-- Z-ORDER recommendation (run post-load):
-- OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id, payment_date);
