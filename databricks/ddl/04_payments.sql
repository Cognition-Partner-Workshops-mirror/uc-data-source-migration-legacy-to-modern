-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Payment history fact table. High-volume table partitioned by payment_year
-- (derived from payment_date) to optimize time-range queries common in
-- loan servicing and reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Primary key (auto-generated surrogate key)
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy sequence reference (CDW_PMT_HIST.PMT_SEQ_NBR) for traceability
    legacy_payment_id   STRING,

    -- Foreign key to loan_accounts (resolved from LN_ACCT_NBR → loan_accounts.id)
    loan_account_id     BIGINT NOT NULL,

    -- Payment date (parsed from MM/DD/YYYY string)
    payment_date        DATE NOT NULL,

    -- Payment amounts (parsed from comma-formatted VARCHAR strings)
    total_amount        DECIMAL(10, 2) NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2) DEFAULT 0,

    -- Payment type (expanded: REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment)
    type                STRING NOT NULL,

    -- Payment status (expanded: PST→Posted, REV→Reversed, NSF→NSF, PND→Pending)
    status              STRING NOT NULL,

    -- Processing dates (parsed from MM/DD/YYYY strings)
    received_date       DATE,
    processed_date      DATE,

    -- Audit timestamps
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Partition column (derived from payment_date for time-based partitioning)
    payment_year        INT GENERATED ALWAYS AS (YEAR(payment_date)),

    -- Constraints
    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT fk_payments_loan_account FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id)
)
USING DELTA
PARTITIONED BY (payment_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment_year for efficient time-range queries in loan servicing and reporting.';
