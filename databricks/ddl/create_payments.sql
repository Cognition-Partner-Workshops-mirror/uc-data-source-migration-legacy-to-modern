-- =============================================================================
-- Delta Lake Table: payments (Fact)
-- =============================================================================
-- Source: CDW_PMT_HIST (legacy all-VARCHAR payment history table)
-- Mapped via: data/mappings/column_mappings.md
--
-- Key transformations from legacy:
--   - LN_ACCT_NBR resolved to loan_account_id FK referencing loan_accounts table
--   - All amount VARCHARs (PMT_AMT, PMT_PRIN_AMT, etc.) → DECIMAL
--   - All date VARCHARs (PMT_DT, PMT_RECV_DT, etc.) → DATE
--   - PMT_TYP_CD expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
--   - PMT_STAT_CD expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
--   - PMT_SEQ_NBR preserved as legacy_payment_id for audit trail
--
-- Partitioning: by payment_year (extracted from payment_date) — enables
--   efficient time-range queries for payment history analysis
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    payment_id          BIGINT              COMMENT 'Surrogate primary key',

    -- Legacy identifier preserved for traceability
    legacy_payment_id   STRING              COMMENT 'Original PMT_SEQ_NBR from CDW_PMT_HIST (e.g., PMT-2025120001)',

    -- Foreign key (resolved from legacy LN_ACCT_NBR)
    loan_account_id     BIGINT NOT NULL      COMMENT 'FK to loan_accounts.loan_account_id (resolved from LN_ACCT_NBR)',

    -- Payment financial fields (parsed from comma-formatted VARCHAR strings)
    payment_date        DATE   NOT NULL      COMMENT 'Payment due date (from PMT_DT)',
    total_amount        DECIMAL(10, 2) NOT NULL  COMMENT 'Total payment amount (from PMT_AMT)',
    principal_amount    DECIMAL(10, 2)       COMMENT 'Principal portion (from PMT_PRIN_AMT)',
    interest_amount     DECIMAL(10, 2)       COMMENT 'Interest portion (from PMT_INT_AMT)',
    escrow_amount       DECIMAL(10, 2)       COMMENT 'Escrow portion (from PMT_ESCROW_AMT)',
    late_fee            DECIMAL(10, 2) DEFAULT 0  COMMENT 'Late fee charged (from PMT_LATE_FEE)',

    -- Payment classification (expanded from abbreviations)
    type                STRING NOT NULL       COMMENT 'Payment type: REGULAR, EXTRA, PARTIAL, PREPAYMENT (from PMT_TYP_CD)',
    status              STRING NOT NULL       COMMENT 'Payment status: POSTED, REVERSED, NSF, PENDING (from PMT_STAT_CD)',

    -- Processing dates (parsed from MM/DD/YYYY VARCHARs)
    received_date       DATE                 COMMENT 'Date payment was received (from PMT_RECV_DT)',
    processed_date      DATE                 COMMENT 'Date payment was processed (from PMT_PROC_DT)',

    -- Audit timestamps
    created_at          TIMESTAMP            COMMENT 'Record creation timestamp (from PMT_CRET_DT)',
    updated_at          TIMESTAMP            COMMENT 'Last update timestamp (from PMT_UPDT_DT)',

    -- ETL metadata
    _ingestion_ts       TIMESTAMP            COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING               COMMENT 'Source system identifier (CDW_PMT_HIST)',

    -- Partition column derived from payment_date for efficient time-range queries
    payment_year        INT                  COMMENT 'Year extracted from payment_date for partitioning'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Properly typed amounts and dates, expanded status/type codes, FK to loan_accounts. Partitioned by payment year for efficient historical queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
