-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_PMT_HIST → payments
-- Key transformations:
--   - PMT_SEQ_NBR preserved as legacy_payment_id for traceability
--   - LN_ACCT_NBR → loan_account_id (BIGINT FK via loan_accounts.account_number lookup)
--   - All amount VARCHARs → DECIMAL (commas stripped)
--   - All date VARCHARs → DATE (parsed from MM/DD/YYYY)
--   - PMT_TYP_CD expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
--   - PMT_STAT_CD expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
-- Partitioning: by status — supports efficient queries for posted vs pending payments
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT         GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING         NOT NULL COMMENT 'Legacy PMT_SEQ_NBR — preserved for audit traceability',
    loan_account_id     BIGINT         NOT NULL COMMENT 'FK to loan_accounts.loan_account_id — resolved from legacy LN_ACCT_NBR',
    payment_date        DATE           NOT NULL COMMENT 'Legacy PMT_DT — parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10,2)  NOT NULL COMMENT 'Legacy PMT_AMT — parsed from comma-separated string',
    principal_amount    DECIMAL(10,2)  NOT NULL COMMENT 'Legacy PMT_PRIN_AMT — parsed from comma-separated string',
    interest_amount     DECIMAL(10,2)  NOT NULL COMMENT 'Legacy PMT_INT_AMT — parsed from comma-separated string',
    escrow_amount       DECIMAL(10,2)  DEFAULT 0.00 COMMENT 'Legacy PMT_ESCROW_AMT — parsed from comma-separated string',
    late_fee            DECIMAL(10,2)  DEFAULT 0.00 COMMENT 'Legacy PMT_LATE_FEE — parsed from comma-separated string',
    type                STRING         NOT NULL COMMENT 'Legacy PMT_TYP_CD expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING         NOT NULL COMMENT 'Legacy PMT_STAT_CD expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE           COMMENT 'Legacy PMT_RECV_DT — parsed from MM/DD/YYYY',
    processed_date      DATE           COMMENT 'Legacy PMT_PROC_DT — parsed from MM/DD/YYYY',
    created_at          TIMESTAMP      COMMENT 'Legacy PMT_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP      COMMENT 'Legacy PMT_UPDT_DT — parsed from MM/DD/YYYY'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Modern payment history table migrated from legacy CDW_PMT_HIST — FK to loan_accounts replaces string LN_ACCT_NBR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);
