-- =============================================================================
-- Delta Lake DDL: loan_accounts
-- Source: CDW_LN_ACCT (Legacy CDW)
-- =============================================================================
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
-- are dropped during migration. Use borrower_id FK to join borrowers table.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    account_number      STRING          NOT NULL    COMMENT 'Legacy: LN_ACCT_NBR — unique loan account number (natural key)',
    borrower_id         STRING          NOT NULL    COMMENT 'Legacy: BORR_ID — FK to borrowers.external_id',
    product_code        STRING          NOT NULL    COMMENT 'Legacy: PROD_CD — FK to loan_products.code',
    original_amount     DECIMAL(12, 2)  NOT NULL    COMMENT 'Legacy: LN_ORIG_AMT — parsed from comma-formatted string',
    current_balance     DECIMAL(12, 2)  NOT NULL    COMMENT 'Legacy: LN_CURR_BAL — parsed from comma-formatted string',
    interest_rate       DECIMAL(5, 3)   NOT NULL    COMMENT 'Legacy: LN_INT_RT — parsed from VARCHAR to decimal',
    term_months         INT             NOT NULL    COMMENT 'Legacy: LN_TERM_MOS — parsed from VARCHAR to integer',
    monthly_payment     DECIMAL(10, 2)  NOT NULL    COMMENT 'Legacy: LN_PMT_AMT — parsed from comma-formatted string',
    origination_date    DATE            NOT NULL    COMMENT 'Legacy: LN_ORIG_DT — parsed from MM/DD/YYYY string',
    maturity_date       DATE            NOT NULL    COMMENT 'Legacy: LN_MAT_DT — parsed from MM/DD/YYYY string',
    first_payment_date  DATE                        COMMENT 'Legacy: LN_1ST_PMT_DT — parsed from MM/DD/YYYY string',
    next_payment_date   DATE                        COMMENT 'Legacy: LN_NXT_PMT_DT — parsed from MM/DD/YYYY string',
    status              STRING                      COMMENT 'Legacy: LN_STAT_CD — expanded ACT/CLO/DFT/FRB to full status',
    delinquency_days    INT                         COMMENT 'Legacy: LN_DLQ_DAYS — parsed from VARCHAR to integer',
    escrow_balance      DECIMAL(10, 2)              COMMENT 'Legacy: LN_ESCROW_BAL — parsed from comma-formatted string',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Legacy: LN_LTV_PCT — loan-to-value ratio percentage',
    property_address    STRING                      COMMENT 'Legacy: PROP_ADDR_LN1 — property street address',
    property_city       STRING                      COMMENT 'Legacy: PROP_CTY_NM — property city',
    property_state      STRING                      COMMENT 'Legacy: PROP_ST_CD — property two-letter state code',
    property_zip        STRING                      COMMENT 'Legacy: PROP_ZIP_CD — property ZIP code',
    property_type       STRING                      COMMENT 'Legacy: PROP_TYP_CD — expanded SFR/CND/MFR/TWN to full name',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Legacy: PROP_APRS_VAL — parsed from comma-formatted string',
    created_at          TIMESTAMP                   COMMENT 'Legacy: LN_CRET_DT — parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Legacy: LN_UPDT_DT — parsed from MM/DD/YYYY string',
    origination_year    INT                         COMMENT 'Derived partition key: year from origination_date',
    _migration_source   STRING                      COMMENT 'Source system identifier for lineage tracking',
    _migrated_at        TIMESTAMP                   COMMENT 'Timestamp when record was migrated'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account data migrated from CDW_LN_ACCT. Denormalized borrower fields removed; use borrower_id FK. Partitioned by status for common loan status filter queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
