-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy Corporate Data Warehouse)
-- =============================================================================
-- Payment history fact table. Partitioned by payment_year for efficient
-- time-range queries on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          STRING          NOT NULL    COMMENT 'Legacy PMT_SEQ_NBR — unique payment identifier',
    loan_account_number STRING          NOT NULL    COMMENT 'FK to loan_accounts.account_number (from LN_ACCT_NBR)',
    payment_date        DATE            NOT NULL    COMMENT 'Parsed from PMT_DT MM/DD/YYYY string',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from PMT_AMT — commas removed',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Parsed from PMT_PRIN_AMT — commas removed',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Parsed from PMT_INT_AMT — commas removed',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Parsed from PMT_ESCROW_AMT — commas removed',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from PMT_LATE_FEE — commas removed',
    type                STRING          NOT NULL    COMMENT 'Expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'Expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE                        COMMENT 'Parsed from PMT_RECV_DT MM/DD/YYYY string',
    processed_date      DATE                        COMMENT 'Parsed from PMT_PROC_DT MM/DD/YYYY string',
    component_sum_valid BOOLEAN         NOT NULL    COMMENT 'True if principal+interest+escrow+late_fee == total_amount (within $0.02)',
    payment_year        INT             NOT NULL    COMMENT 'Derived partition key: YEAR(payment_date)',
    created_at          TIMESTAMP                   COMMENT 'Parsed from PMT_CRET_DT MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from PMT_UPDT_DT MM/DD/YYYY string',
    _ingestion_ts       TIMESTAMP       NOT NULL    COMMENT 'Pipeline ingestion timestamp',
    _source_file        STRING                      COMMENT 'Source file path for lineage tracking'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table — migrated from legacy CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
