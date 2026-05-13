-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts — denormalized)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_ACCT → loan_accounts
-- Key transformations:
--   - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped;
--     replaced by borrower_id FK to borrowers table
--   - PROD_CD → product_id FK lookup via loan_products.code
--   - All VARCHAR amounts → DECIMAL (commas stripped)
--   - All VARCHAR dates → DATE (MM/DD/YYYY parsed)
--   - LN_STAT_CD → status (expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE)
--   - PROP_TYP_CD → property_type (expanded: SFR→Single Family, etc.)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL    COMMENT 'Loan account number (from LN_ACCT_NBR)',
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.id (resolved from BORR_ID via external_id lookup)',
    product_id          BIGINT          NOT NULL    COMMENT 'FK to loan_products.id (resolved from PROD_CD via code lookup)',
    original_amount     DECIMAL(12, 2)              COMMENT 'Parsed from LN_ORIG_AMT (remove commas → DECIMAL)',
    current_balance     DECIMAL(12, 2)              COMMENT 'Parsed from LN_CURR_BAL (remove commas → DECIMAL)',
    interest_rate       DECIMAL(5, 3)               COMMENT 'Parsed from LN_INT_RT (VARCHAR → DECIMAL)',
    term_months         INT                         COMMENT 'Parsed from LN_TERM_MOS (VARCHAR → INT)',
    monthly_payment     DECIMAL(10, 2)              COMMENT 'Parsed from LN_PMT_AMT (remove commas → DECIMAL)',
    origination_date    DATE                        COMMENT 'Parsed from LN_ORIG_DT (MM/DD/YYYY → DATE)',
    maturity_date       DATE                        COMMENT 'Parsed from LN_MAT_DT (MM/DD/YYYY → DATE)',
    first_payment_date  DATE                        COMMENT 'Parsed from LN_1ST_PMT_DT (MM/DD/YYYY → DATE)',
    next_payment_date   DATE                        COMMENT 'Parsed from LN_NXT_PMT_DT (MM/DD/YYYY → DATE)',
    status              STRING          NOT NULL    COMMENT 'Expanded from LN_STAT_CD: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT             DEFAULT 0   COMMENT 'Parsed from LN_DLQ_DAYS (VARCHAR → INT)',
    escrow_balance      DECIMAL(10, 2)              COMMENT 'Parsed from LN_ESCROW_BAL (remove commas → DECIMAL)',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Parsed from LN_LTV_PCT (VARCHAR → DECIMAL)',
    property_address    STRING                      COMMENT 'Property street address (from PROP_ADDR_LN1)',
    property_city       STRING                      COMMENT 'Property city (from PROP_CTY_NM)',
    property_state      STRING                      COMMENT 'Property 2-letter state (from PROP_ST_CD)',
    property_zip        STRING                      COMMENT 'Property ZIP code (from PROP_ZIP_CD)',
    property_type       STRING                      COMMENT 'Expanded from PROP_TYP_CD: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Parsed from PROP_APRS_VAL (remove commas → DECIMAL)',
    created_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from LN_CRET_DT (MM/DD/YYYY → TIMESTAMP)',
    updated_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from LN_UPDT_DT (MM/DD/YYYY → TIMESTAMP)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT'       COMMENT 'Source table identifier'
)
USING DELTA
-- Partitioned by status to optimize common queries filtering on active/closed loans.
-- Origination year considered but status has lower cardinality and higher query relevance.
PARTITIONED BY (status)
COMMENT 'Normalized loan accounts table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields replaced by FK. All VARCHAR fields converted to proper types.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
