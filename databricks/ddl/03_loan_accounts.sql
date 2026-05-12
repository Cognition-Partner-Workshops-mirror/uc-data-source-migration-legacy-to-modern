-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts — denormalized)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_ACCT → loan_accounts
-- Key transformations:
--   - Denormalized BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 dropped (use borrower FK)
--   - BORR_ID (VARCHAR) → borrower_id (BIGINT FK via borrowers.external_id lookup)
--   - PROD_CD (VARCHAR) → product_id (BIGINT FK via loan_products.code lookup)
--   - All amount VARCHARs → DECIMAL (commas stripped)
--   - All date VARCHARs → DATE (parsed from MM/DD/YYYY)
--   - LN_STAT_CD expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
--   - PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, etc.
-- Partitioning: by status — common filter in queries, good cardinality (4 values)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id    BIGINT         GENERATED ALWAYS AS IDENTITY,
    account_number     STRING         NOT NULL COMMENT 'Legacy LN_ACCT_NBR (e.g. LN-2019-00142)',
    borrower_id        BIGINT         NOT NULL COMMENT 'FK to borrowers.borrower_id — resolved from legacy BORR_ID',
    product_id         BIGINT         NOT NULL COMMENT 'FK to loan_products.product_id — resolved from legacy PROD_CD',
    original_amount    DECIMAL(12,2)  NOT NULL COMMENT 'Legacy LN_ORIG_AMT — parsed from comma-separated string',
    current_balance    DECIMAL(12,2)  NOT NULL COMMENT 'Legacy LN_CURR_BAL — parsed from comma-separated string',
    interest_rate      DECIMAL(5,3)   NOT NULL COMMENT 'Legacy LN_INT_RT — parsed from string (e.g. "4.750")',
    term_months        INT            NOT NULL COMMENT 'Legacy LN_TERM_MOS — parsed from VARCHAR',
    monthly_payment    DECIMAL(10,2)  NOT NULL COMMENT 'Legacy LN_PMT_AMT — parsed from comma-separated string',
    origination_date   DATE           NOT NULL COMMENT 'Legacy LN_ORIG_DT — parsed from MM/DD/YYYY',
    maturity_date      DATE           NOT NULL COMMENT 'Legacy LN_MAT_DT — parsed from MM/DD/YYYY',
    first_payment_date DATE           COMMENT 'Legacy LN_1ST_PMT_DT — parsed from MM/DD/YYYY',
    next_payment_date  DATE           COMMENT 'Legacy LN_NXT_PMT_DT — parsed from MM/DD/YYYY',
    status             STRING         NOT NULL COMMENT 'Legacy LN_STAT_CD expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days   INT            DEFAULT 0 COMMENT 'Legacy LN_DLQ_DAYS — parsed from VARCHAR',
    escrow_balance     DECIMAL(10,2)  COMMENT 'Legacy LN_ESCROW_BAL — parsed from comma-separated string',
    ltv_percent        DECIMAL(5,2)   COMMENT 'Legacy LN_LTV_PCT — parsed from string (e.g. "82.5")',
    property_address   STRING         COMMENT 'Legacy PROP_ADDR_LN1',
    property_city      STRING         COMMENT 'Legacy PROP_CTY_NM',
    property_state     STRING         COMMENT 'Legacy PROP_ST_CD — 2-letter code',
    property_zip       STRING         COMMENT 'Legacy PROP_ZIP_CD',
    property_type      STRING         COMMENT 'Legacy PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value    DECIMAL(12,2)  COMMENT 'Legacy PROP_APRS_VAL — parsed from comma-separated string',
    created_at         TIMESTAMP      COMMENT 'Legacy LN_CRET_DT — parsed from MM/DD/YYYY',
    updated_at         TIMESTAMP      COMMENT 'Legacy LN_UPDT_DT — parsed from MM/DD/YYYY'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Modern loan accounts table migrated from legacy CDW_LN_ACCT — denormalized borrower fields removed, FKs to borrowers and loan_products added'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);
