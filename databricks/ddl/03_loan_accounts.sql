-- =============================================================================
-- Delta Lake Table: loan_accounts
-- =============================================================================
-- Migrated from legacy CDW_LN_ACCT table.
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
-- have been dropped; borrower_id FK references the borrowers table instead.
-- Loan status codes expanded: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance.
-- Property type codes expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse.
-- All amount/rate/percentage strings parsed to DECIMAL types.
-- All date strings (MM/DD/YYYY) parsed to DATE or TIMESTAMP types.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key generated during ingestion
    loan_account_id     BIGINT              COMMENT 'Auto-generated surrogate primary key',
    -- Natural key carried from legacy CDW_LN_ACCT.LN_ACCT_NBR
    account_number      STRING NOT NULL      COMMENT 'Loan account number from CDW_LN_ACCT.LN_ACCT_NBR',
    -- Foreign key to borrowers table (resolved from CDW_LN_ACCT.BORR_ID)
    borrower_id         BIGINT NOT NULL      COMMENT 'FK to borrowers.borrower_id, resolved via BORR_ID lookup',
    -- Foreign key to loan_products table (resolved from CDW_LN_ACCT.PROD_CD)
    product_id          BIGINT NOT NULL      COMMENT 'FK to loan_products.product_id, resolved via PROD_CD lookup',
    -- Loan financial details
    original_amount     DECIMAL(12, 2) NOT NULL  COMMENT 'Parsed from LN_ORIG_AMT (comma-formatted string -> DECIMAL)',
    current_balance     DECIMAL(12, 2) NOT NULL  COMMENT 'Parsed from LN_CURR_BAL (comma-formatted string -> DECIMAL)',
    interest_rate       DECIMAL(5, 3)  NOT NULL  COMMENT 'Parsed from LN_INT_RT (string -> DECIMAL)',
    term_months         INT            NOT NULL  COMMENT 'Parsed from LN_TERM_MOS (VARCHAR -> INT)',
    monthly_payment     DECIMAL(10, 2) NOT NULL  COMMENT 'Parsed from LN_PMT_AMT (comma-formatted string -> DECIMAL)',
    -- Loan dates
    origination_date    DATE NOT NULL        COMMENT 'Parsed from LN_ORIG_DT (MM/DD/YYYY -> DATE)',
    maturity_date       DATE NOT NULL        COMMENT 'Parsed from LN_MAT_DT (MM/DD/YYYY -> DATE)',
    first_payment_date  DATE                 COMMENT 'Parsed from LN_1ST_PMT_DT (MM/DD/YYYY -> DATE)',
    next_payment_date   DATE                 COMMENT 'Parsed from LN_NXT_PMT_DT (MM/DD/YYYY -> DATE)',
    -- Loan status and delinquency
    status              STRING               COMMENT 'Expanded from LN_STAT_CD: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT DEFAULT 0        COMMENT 'Parsed from LN_DLQ_DAYS (VARCHAR -> INT)',
    escrow_balance      DECIMAL(10, 2) DEFAULT 0  COMMENT 'Parsed from LN_ESCROW_BAL (comma-formatted string -> DECIMAL)',
    ltv_percent         DECIMAL(5, 2)        COMMENT 'Parsed from LN_LTV_PCT (string -> DECIMAL)',
    -- Property information
    property_address    STRING               COMMENT 'Mapped from PROP_ADDR_LN1',
    property_city       STRING               COMMENT 'Mapped from PROP_CTY_NM',
    property_state      STRING               COMMENT 'Mapped from PROP_ST_CD',
    property_zip        STRING               COMMENT 'Mapped from PROP_ZIP_CD',
    property_type       STRING               COMMENT 'Expanded from PROP_TYP_CD: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2)       COMMENT 'Parsed from PROP_APRS_VAL (comma-formatted string -> DECIMAL)',
    -- Audit timestamps
    created_at          TIMESTAMP            COMMENT 'Parsed from LN_CRET_DT (MM/DD/YYYY -> TIMESTAMP)',
    updated_at          TIMESTAMP            COMMENT 'Parsed from LN_UPDT_DT (MM/DD/YYYY -> TIMESTAMP)',
    -- Ingestion metadata
    _ingestion_ts       TIMESTAMP            COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING               COMMENT 'Source system identifier (CDW_LN_ACCT)',
    -- Partition column derived from origination_date during ingestion
    origination_year    INT                  COMMENT 'Derived year from origination_date for partitioning'
)
USING DELTA
-- Partitioned by status for efficient filtering of active vs closed loans
-- Also partitioned by origination year for time-based queries and data lifecycle management
PARTITIONED BY (status, origination_year)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Normalized: borrower fields removed, FK references used instead.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
