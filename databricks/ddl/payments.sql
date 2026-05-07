-- =============================================================================
-- Delta Lake DDL: payments
-- Source: CDW_PMT_HIST (Legacy CDW)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_sequence    STRING          NOT NULL    COMMENT 'Legacy: PMT_SEQ_NBR — original payment sequence identifier',
    loan_account_number STRING          NOT NULL    COMMENT 'Legacy: LN_ACCT_NBR — FK to loan_accounts.account_number',
    payment_date        DATE            NOT NULL    COMMENT 'Legacy: PMT_DT — parsed from MM/DD/YYYY string',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Legacy: PMT_AMT — parsed from comma-formatted string',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Legacy: PMT_PRIN_AMT — parsed from comma-formatted string',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Legacy: PMT_INT_AMT — parsed from comma-formatted string',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Legacy: PMT_ESCROW_AMT — parsed from comma-formatted string',
    late_fee            DECIMAL(10, 2)              COMMENT 'Legacy: PMT_LATE_FEE — parsed from comma-formatted string',
    type                STRING          NOT NULL    COMMENT 'Legacy: PMT_TYP_CD — expanded REG/EXT/PRT/PRE to full name',
    status              STRING          NOT NULL    COMMENT 'Legacy: PMT_STAT_CD — expanded PST/REV/NSF/PND to full name',
    received_date       DATE                        COMMENT 'Legacy: PMT_RECV_DT — parsed from MM/DD/YYYY string',
    processed_date      DATE                        COMMENT 'Legacy: PMT_PROC_DT — parsed from MM/DD/YYYY string',
    created_at          TIMESTAMP                   COMMENT 'Legacy: PMT_CRET_DT — parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Legacy: PMT_UPDT_DT — parsed from MM/DD/YYYY string',
    payment_year_month  STRING                      COMMENT 'Derived partition key: YYYY-MM from payment_date',
    _migration_source   STRING                      COMMENT 'Source system identifier for lineage tracking',
    _migrated_at        TIMESTAMP                   COMMENT 'Timestamp when record was migrated'
)
USING DELTA
PARTITIONED BY (payment_year_month)
COMMENT 'Payment history migrated from CDW_PMT_HIST. Partitioned by payment year-month for time-range queries on transaction data.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
