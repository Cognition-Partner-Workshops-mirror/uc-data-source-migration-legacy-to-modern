-- =============================================================================
-- Delta Lake Table: loan_accounts (Fact)
-- =============================================================================
-- Source: CDW_LN_ACCT (legacy denormalized, all-VARCHAR loan account table)
-- Mapped via: data/mappings/column_mappings.md
--
-- Key transformations from legacy:
--   - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped;
--     replaced by borrower_id FK referencing borrowers table
--   - PROD_CD resolved to product_id FK referencing loan_products table
--   - All amount VARCHARs (LN_ORIG_AMT, LN_CURR_BAL, etc.) → DECIMAL
--   - All date VARCHARs (LN_ORIG_DT, LN_MAT_DT, etc.) → DATE
--   - LN_STAT_CD expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
--   - PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse
--
-- Partitioning: by status — enables efficient queries for active vs. closed loans
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    loan_account_id     BIGINT              COMMENT 'Surrogate primary key',

    -- Natural key from legacy CDW_LN_ACCT.LN_ACCT_NBR
    account_number      STRING NOT NULL      COMMENT 'Loan account number (e.g., LN-2019-00142)',

    -- Foreign keys (resolved from legacy string IDs)
    borrower_id         BIGINT NOT NULL      COMMENT 'FK to borrowers.borrower_id (resolved from BORR_ID via external_id lookup)',
    product_id          BIGINT NOT NULL      COMMENT 'FK to loan_products.product_id (resolved from PROD_CD via code lookup)',

    -- Loan financial fields (parsed from comma-formatted VARCHAR strings)
    original_amount     DECIMAL(12, 2) NOT NULL  COMMENT 'Original loan amount (from LN_ORIG_AMT)',
    current_balance     DECIMAL(12, 2) NOT NULL  COMMENT 'Current outstanding balance (from LN_CURR_BAL)',
    interest_rate       DECIMAL(5, 3) NOT NULL   COMMENT 'Annual interest rate (from LN_INT_RT)',
    term_months         INT            NOT NULL   COMMENT 'Loan term in months (from LN_TERM_MOS)',
    monthly_payment     DECIMAL(10, 2) NOT NULL  COMMENT 'Monthly payment amount (from LN_PMT_AMT)',

    -- Loan date fields (parsed from MM/DD/YYYY VARCHARs)
    origination_date    DATE NOT NULL        COMMENT 'Loan origination date (from LN_ORIG_DT)',
    maturity_date       DATE NOT NULL        COMMENT 'Loan maturity date (from LN_MAT_DT)',
    first_payment_date  DATE                 COMMENT 'First payment due date (from LN_1ST_PMT_DT)',
    next_payment_date   DATE                 COMMENT 'Next payment due date (from LN_NXT_PMT_DT)',

    -- Loan status (expanded from abbreviations)
    status              STRING               COMMENT 'Loan status: ACTIVE, CLOSED, DEFAULT, FORBEARANCE (from LN_STAT_CD)',
    delinquency_days    INT DEFAULT 0        COMMENT 'Days delinquent (from LN_DLQ_DAYS)',
    escrow_balance      DECIMAL(10, 2) DEFAULT 0  COMMENT 'Escrow account balance (from LN_ESCROW_BAL)',
    ltv_percent         DECIMAL(5, 2)        COMMENT 'Loan-to-value ratio (from LN_LTV_PCT)',

    -- Property fields
    property_address    STRING               COMMENT 'Property street address (from PROP_ADDR_LN1)',
    property_city       STRING               COMMENT 'Property city (from PROP_CTY_NM)',
    property_state      STRING               COMMENT 'Property state (from PROP_ST_CD)',
    property_zip        STRING               COMMENT 'Property ZIP code (from PROP_ZIP_CD)',
    property_type       STRING               COMMENT 'Property type: Single Family, Condominium, Multi-Family, Townhouse (from PROP_TYP_CD)',
    appraised_value     DECIMAL(12, 2)       COMMENT 'Property appraised value (from PROP_APRS_VAL)',

    -- Audit timestamps
    created_at          TIMESTAMP            COMMENT 'Record creation timestamp (from LN_CRET_DT)',
    updated_at          TIMESTAMP            COMMENT 'Last update timestamp (from LN_UPDT_DT)',

    -- ETL metadata
    _ingestion_ts       TIMESTAMP            COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING               COMMENT 'Source system identifier (CDW_LN_ACCT)'
)
USING DELTA
-- Partition by status: most queries filter on active vs. closed loans
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Normalized (borrower fields removed), properly typed, with FK references to borrowers and loan_products. Partitioned by loan status for query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
