-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_ACCT → loan_accounts
-- Partitioned by origination_year for time-based query optimization.
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
-- are dropped; use borrower_id FK to join with borrowers table instead.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR (e.g., LN-2019-00142)',
    borrower_id         BIGINT          NOT NULL COMMENT 'FK to borrowers.borrower_id, resolved from BORR_ID',
    product_id          BIGINT          NOT NULL COMMENT 'FK to loan_products.product_id, resolved from PROD_CD',
    original_amount     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_ORIG_AMT, parsed from comma-formatted string',
    current_balance     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_CURR_BAL, parsed from comma-formatted string',
    interest_rate       DECIMAL(5, 3)   NOT NULL COMMENT 'Legacy LN_INT_RT, parsed from VARCHAR',
    term_months         INT             NOT NULL COMMENT 'Legacy LN_TERM_MOS, parsed from VARCHAR',
    monthly_payment     DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy LN_PMT_AMT, parsed from comma-formatted string',
    origination_date    DATE            NOT NULL COMMENT 'Legacy LN_ORIG_DT, parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL COMMENT 'Legacy LN_MAT_DT, parsed from MM/DD/YYYY',
    first_payment_date  DATE            COMMENT 'Legacy LN_1ST_PMT_DT, parsed from MM/DD/YYYY',
    next_payment_date   DATE            COMMENT 'Legacy LN_NXT_PMT_DT, parsed from MM/DD/YYYY',
    status              STRING          NOT NULL COMMENT 'Expanded from LN_STAT_CD: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT             DEFAULT 0 COMMENT 'Legacy LN_DLQ_DAYS, parsed from VARCHAR',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0.00 COMMENT 'Legacy LN_ESCROW_BAL, parsed from comma-formatted string',
    ltv_percent         DECIMAL(5, 2)   COMMENT 'Legacy LN_LTV_PCT, loan-to-value ratio',
    property_address    STRING          COMMENT 'Legacy PROP_ADDR_LN1',
    property_city       STRING          COMMENT 'Legacy PROP_CTY_NM',
    property_state      STRING          COMMENT 'Legacy PROP_ST_CD',
    property_zip        STRING          COMMENT 'Legacy PROP_ZIP_CD',
    property_type       STRING          COMMENT 'Expanded from PROP_TYP_CD: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)  COMMENT 'Legacy PROP_APRS_VAL, parsed from comma-formatted string',
    created_at          TIMESTAMP       COMMENT 'Legacy LN_CRET_DT, parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy LN_UPDT_DT, parsed from MM/DD/YYYY',
    origination_year    INT             NOT NULL COMMENT 'Derived from origination_date for partitioning',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan account data migrated from legacy CDW_LN_ACCT table. Denormalized borrower fields removed; use borrower_id FK.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
