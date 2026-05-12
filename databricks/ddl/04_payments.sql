-- =============================================================================
-- Delta Lake Table: payments (fact table)
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Migrated from the legacy CDW_PMT_HIST table. All VARCHAR amounts are parsed
-- to DECIMAL. Payment type codes expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL,
-- PRE→PREPAYMENT. Payment status codes expanded: PST→POSTED, REV→REVERSED,
-- NSF→NSF, PND→PENDING. Partitioned by payment_date (year/month) for
-- efficient time-range queries on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy PMT_SEQ_NBR preserved for traceability
    legacy_payment_id   STRING
        COMMENT 'Legacy PMT_SEQ_NBR from CDW_PMT_HIST for audit trail',

    -- FK to loan_accounts table, resolved from legacy LN_ACCT_NBR
    loan_account_id     BIGINT          NOT NULL
        COMMENT 'FK to loan_accounts.id; resolved from legacy LN_ACCT_NBR',

    -- Parsed from MM/DD/YYYY string (legacy: PMT_DT)
    payment_date        DATE            NOT NULL
        COMMENT 'Payment date, parsed from legacy MM/DD/YYYY string',

    -- Financial fields parsed from comma-formatted VARCHAR strings
    total_amount        DECIMAL(10, 2)  NOT NULL
        COMMENT 'Total payment amount, parsed from legacy PMT_AMT',
    principal_amount    DECIMAL(10, 2)
        COMMENT 'Principal portion, parsed from legacy PMT_PRIN_AMT',
    interest_amount     DECIMAL(10, 2)
        COMMENT 'Interest portion, parsed from legacy PMT_INT_AMT',
    escrow_amount       DECIMAL(10, 2)
        COMMENT 'Escrow portion, parsed from legacy PMT_ESCROW_AMT',
    late_fee            DECIMAL(10, 2)  DEFAULT 0
        COMMENT 'Late fee amount, parsed from legacy PMT_LATE_FEE',

    -- Expanded from abbreviation (legacy: PMT_TYP_CD)
    -- REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
    type                STRING          NOT NULL
        COMMENT 'Payment type: REGULAR, EXTRA, PARTIAL, or PREPAYMENT',

    -- Expanded from abbreviation (legacy: PMT_STAT_CD)
    -- PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
    status              STRING          NOT NULL
        COMMENT 'Payment status: POSTED, REVERSED, NSF, or PENDING',

    -- Date fields parsed from MM/DD/YYYY strings
    received_date       DATE
        COMMENT 'Date payment was received, parsed from legacy PMT_RECV_DT',
    processed_date      DATE
        COMMENT 'Date payment was processed, parsed from legacy PMT_PROC_DT',

    -- Parsed from MM/DD/YYYY strings
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Audit column
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
        COMMENT 'Timestamp when the row was loaded by the migration pipeline'
)
USING DELTA
-- Partition by year extracted from payment_date for efficient time-range queries
PARTITIONED BY (payment_year INT)
COMMENT 'Modern payments fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
