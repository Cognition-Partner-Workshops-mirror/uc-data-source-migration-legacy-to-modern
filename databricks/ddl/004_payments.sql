-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction table. Converts all VARCHAR amount fields to DECIMAL
-- and date strings to DATE. Expands cryptic type/status codes to readable
-- values. Partitioned by status for efficient filtering of posted vs. pending
-- payments in operational queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          COMMENT 'Original PMT_SEQ_NBR from CDW_PMT_HIST for traceability',
    loan_account_id     BIGINT          NOT NULL
        COMMENT 'FK to loan_accounts.loan_account_id, resolved from legacy LN_ACCT_NBR via account_number lookup',
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,
    type                STRING          NOT NULL
        COMMENT 'Expanded from legacy codes: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    status              STRING          NOT NULL
        COMMENT 'Expanded from legacy codes: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Payment history table migrated from legacy CDW_PMT_HIST. Partitioned by status.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality'                          = 'gold'
);
