-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (legacy Corporate Data Warehouse)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table are dropped — use borrower_id FK to join to borrowers table.
-- Partitioned by origination_year for time-range queries and data lifecycle.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    account_number      STRING          NOT NULL    COMMENT 'Legacy LN_ACCT_NBR — unique loan identifier',
    borrower_id         STRING          NOT NULL    COMMENT 'FK to borrowers.borrower_id (from BORR_ID)',
    product_code        STRING          NOT NULL    COMMENT 'FK to loan_products.product_code (from PROD_CD)',
    original_amount     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from LN_ORIG_AMT — commas removed',
    current_balance     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from LN_CURR_BAL — commas removed',
    interest_rate       DECIMAL(5, 3)   NOT NULL    COMMENT 'Parsed from LN_INT_RT VARCHAR to decimal',
    term_months         INT             NOT NULL    COMMENT 'Parsed from LN_TERM_MOS VARCHAR to integer',
    monthly_payment     DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from LN_PMT_AMT — commas removed',
    origination_date    DATE            NOT NULL    COMMENT 'Parsed from LN_ORIG_DT MM/DD/YYYY string',
    maturity_date       DATE            NOT NULL    COMMENT 'Parsed from LN_MAT_DT MM/DD/YYYY string',
    first_payment_date  DATE                        COMMENT 'Parsed from LN_1ST_PMT_DT MM/DD/YYYY string',
    next_payment_date   DATE                        COMMENT 'Parsed from LN_NXT_PMT_DT MM/DD/YYYY string',
    status              STRING          NOT NULL    COMMENT 'Expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT             DEFAULT 0   COMMENT 'Parsed from LN_DLQ_DAYS VARCHAR to integer',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from LN_ESCROW_BAL — commas removed',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Parsed from LN_LTV_PCT VARCHAR to decimal',
    property_address    STRING                      COMMENT 'Property address (from PROP_ADDR_LN1)',
    property_city       STRING                      COMMENT 'Property city (from PROP_CTY_NM)',
    property_state      STRING                      COMMENT 'Property state (from PROP_ST_CD)',
    property_zip        STRING                      COMMENT 'Property ZIP (from PROP_ZIP_CD)',
    property_type       STRING                      COMMENT 'Expanded: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Parsed from PROP_APRS_VAL — commas removed',
    origination_year    INT             NOT NULL    COMMENT 'Derived partition key: YEAR(origination_date)',
    created_at          TIMESTAMP                   COMMENT 'Parsed from LN_CRET_DT MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from LN_UPDT_DT MM/DD/YYYY string',
    _ingestion_ts       TIMESTAMP       NOT NULL    COMMENT 'Pipeline ingestion timestamp',
    _source_file        STRING                      COMMENT 'Source file path for lineage tracking'
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan account fact table — migrated from legacy CDW_LN_ACCT (denormalized borrower fields dropped)'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
