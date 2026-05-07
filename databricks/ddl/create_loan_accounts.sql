-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (legacy)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from the legacy
-- table are dropped; borrower_id references the borrowers dimension.
-- Partitioned by status for efficient filtering on active/closed/default queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT        GENERATED ALWAYS AS IDENTITY,
    account_number      STRING        NOT NULL COMMENT 'Legacy LN_ACCT_NBR (e.g. LN-2019-00142)',
    borrower_id         BIGINT        NOT NULL COMMENT 'FK to borrowers — resolved from legacy BORR_ID',
    product_id          BIGINT        NOT NULL COMMENT 'FK to loan_products — resolved from legacy PROD_CD',
    original_amount     DECIMAL(12,2) NOT NULL COMMENT 'Legacy LN_ORIG_AMT — parsed from comma-formatted string',
    current_balance     DECIMAL(12,2) NOT NULL COMMENT 'Legacy LN_CURR_BAL — parsed from comma-formatted string',
    interest_rate       DECIMAL(5,3)  NOT NULL COMMENT 'Legacy LN_INT_RT — parsed from VARCHAR',
    term_months         INT           NOT NULL COMMENT 'Legacy LN_TERM_MOS — parsed from VARCHAR',
    monthly_payment     DECIMAL(10,2) NOT NULL COMMENT 'Legacy LN_PMT_AMT — parsed from comma-formatted string',
    origination_date    DATE          NOT NULL COMMENT 'Legacy LN_ORIG_DT — parsed from MM/DD/YYYY',
    maturity_date       DATE          NOT NULL COMMENT 'Legacy LN_MAT_DT — parsed from MM/DD/YYYY',
    first_payment_date  DATE          COMMENT 'Legacy LN_1ST_PMT_DT — parsed from MM/DD/YYYY',
    next_payment_date   DATE          COMMENT 'Legacy LN_NXT_PMT_DT — parsed from MM/DD/YYYY',
    status              STRING        NOT NULL DEFAULT 'Active' COMMENT 'Legacy LN_STAT_CD expanded: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT           DEFAULT 0 COMMENT 'Legacy LN_DLQ_DAYS — parsed from VARCHAR',
    escrow_balance      DECIMAL(10,2) DEFAULT 0 COMMENT 'Legacy LN_ESCROW_BAL — parsed from comma-formatted string',
    ltv_percent         DECIMAL(5,2)  COMMENT 'Legacy LN_LTV_PCT — parsed from VARCHAR',
    property_address    STRING        COMMENT 'Legacy PROP_ADDR_LN1',
    property_city       STRING        COMMENT 'Legacy PROP_CTY_NM',
    property_state      STRING        COMMENT 'Legacy PROP_ST_CD',
    property_zip        STRING        COMMENT 'Legacy PROP_ZIP_CD',
    property_type       STRING        COMMENT 'Legacy PROP_TYP_CD expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12,2) COMMENT 'Legacy PROP_APRS_VAL — parsed from comma-formatted string',
    created_at          TIMESTAMP     COMMENT 'Legacy LN_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP     COMMENT 'Legacy LN_UPDT_DT — parsed from MM/DD/YYYY',
    _migration_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system      STRING        DEFAULT 'CDW_LN_ACCT' COMMENT 'Source table identifier'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Unique constraint on account number
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_unique UNIQUE (account_number);
