-- =============================================================================
-- Delta Lake Table: payments
-- =============================================================================
-- Source: CDW_PMT_HIST (legacy payment history table)
--
-- Migration notes:
--   - LN_ACCT_NBR resolved to loan_account_id FK referencing loan_accounts table
--   - PMT_SEQ_NBR preserved as legacy_payment_id for audit traceability
--   - All amount fields parsed from comma-formatted strings to DECIMAL
--   - All date fields parsed from MM/DD/YYYY strings to DATE/TIMESTAMP
--   - Payment type codes expanded: REG -> REGULAR, EXT -> EXTRA,
--     PRT -> PARTIAL, PRE -> PREPAYMENT
--   - Payment status codes expanded: PST -> POSTED, REV -> REVERSED,
--     NSF -> NSF, PND -> PENDING
--   - Partitioned by payment_year (derived from payment_date) for efficient
--     time-range queries on payment history
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.payments (
    -- Surrogate primary key
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy PMT_SEQ_NBR preserved for audit trail
    legacy_payment_id   STRING,

    -- FK to loan_accounts table (resolved from LN_ACCT_NBR via account_number lookup)
    loan_account_id     BIGINT        NOT NULL,

    -- Payment date: parsed from MM/DD/YYYY string to DATE
    payment_date        DATE           NOT NULL,

    -- Amount fields: all parsed from comma-formatted strings to DECIMAL
    total_amount        DECIMAL(10, 2) NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2) DEFAULT 0,

    -- Payment type: expanded from abbreviation (REG -> REGULAR, etc.)
    type                STRING         NOT NULL,

    -- Payment status: expanded from abbreviation (PST -> POSTED, etc.)
    status              STRING         NOT NULL,

    -- Processing dates: parsed from MM/DD/YYYY strings to DATE
    received_date       DATE,
    processed_date      DATE,

    -- Derived partition column: extracted year from payment_date
    payment_year        INT,

    -- Audit timestamps: parsed from MM/DD/YYYY strings to TIMESTAMP
    created_at          TIMESTAMP      DEFAULT current_timestamp(),
    updated_at          TIMESTAMP      DEFAULT current_timestamp(),

    -- Constraints (informational for Delta Lake)
    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_management.loan_accounts(id)
)
USING DELTA
-- Partition by payment year for efficient historical payment queries
PARTITIONED BY (payment_year)
COMMENT 'Payment history table migrated from legacy CDW_PMT_HIST. Contains all payment transactions with proper typing and expanded status/type codes. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);
