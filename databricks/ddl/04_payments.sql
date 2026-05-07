-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_PMT_HIST → payments
-- Partitioned by payment_year for time-series query optimization.
-- This is the highest-volume table and benefits most from partitioning.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          NOT NULL COMMENT 'Legacy PMT_SEQ_NBR, preserved for traceability',
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK to loan_accounts.loan_account_id, resolved from LN_ACCT_NBR',
    payment_date        DATE            NOT NULL COMMENT 'Legacy PMT_DT, parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy PMT_AMT, parsed from comma-formatted string',
    principal_amount    DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy PMT_PRIN_AMT',
    interest_amount     DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy PMT_INT_AMT',
    escrow_amount       DECIMAL(10, 2)  DEFAULT 0.00 COMMENT 'Legacy PMT_ESCROW_AMT',
    late_fee            DECIMAL(10, 2)  DEFAULT 0.00 COMMENT 'Legacy PMT_LATE_FEE',
    type                STRING          NOT NULL COMMENT 'Expanded from PMT_TYP_CD: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING          NOT NULL COMMENT 'Expanded from PMT_STAT_CD: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE            COMMENT 'Legacy PMT_RECV_DT, parsed from MM/DD/YYYY',
    processed_date      DATE            COMMENT 'Legacy PMT_PROC_DT, parsed from MM/DD/YYYY',
    created_at          TIMESTAMP       COMMENT 'Legacy PMT_CRET_DT, parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy PMT_UPDT_DT, parsed from MM/DD/YYYY',
    payment_year        INT             NOT NULL COMMENT 'Derived from payment_date for partitioning',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history migrated from legacy CDW_PMT_HIST table. Highest-volume table, partitioned by year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
