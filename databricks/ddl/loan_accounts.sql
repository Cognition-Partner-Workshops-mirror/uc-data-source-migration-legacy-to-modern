-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (legacy denormalized all-VARCHAR loan account table)
-- =============================================================================
-- Normalized loan account fact table. The denormalized borrower columns
-- (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are dropped in favor of a
-- proper foreign key to the borrowers dimension table. Status codes are
-- expanded (ACT -> ACTIVE, CLO -> CLOSED, DFT -> DEFAULT, FRB -> FORBEARANCE)
-- and property type codes are expanded (SFR -> Single Family, etc.).
--
-- Partitioned by status to optimize queries that filter on loan lifecycle
-- stage (most analytical queries segment by active vs. closed vs. default).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Natural key from legacy CDW_LN_ACCT.LN_ACCT_NBR
    account_number      STRING          NOT NULL    COMMENT 'Legacy loan account number (LN_ACCT_NBR)',

    -- Foreign keys (resolved during ingestion from legacy string IDs)
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.id resolved from BORR_ID',
    product_id          BIGINT          NOT NULL    COMMENT 'FK to loan_products.id resolved from PROD_CD',

    -- Financial fields (parsed from comma-formatted VARCHAR strings)
    original_amount     DECIMAL(12,2)   NOT NULL    COMMENT 'Original loan amount (LN_ORIG_AMT)',
    current_balance     DECIMAL(12,2)   NOT NULL    COMMENT 'Current outstanding balance (LN_CURR_BAL)',
    interest_rate       DECIMAL(5,3)    NOT NULL    COMMENT 'Annual interest rate (LN_INT_RT)',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months (LN_TERM_MOS)',
    monthly_payment     DECIMAL(10,2)   NOT NULL    COMMENT 'Monthly payment amount (LN_PMT_AMT)',

    -- Key dates (parsed from MM/DD/YYYY strings)
    origination_date    DATE            NOT NULL    COMMENT 'Loan origination date (LN_ORIG_DT)',
    maturity_date       DATE            NOT NULL    COMMENT 'Loan maturity date (LN_MAT_DT)',
    first_payment_date  DATE            NOT NULL    COMMENT 'First payment due date (LN_1ST_PMT_DT)',
    next_payment_date   DATE            NOT NULL    COMMENT 'Next payment due date (LN_NXT_PMT_DT)',

    -- Loan status (expanded from abbreviation)
    status              STRING          NOT NULL    COMMENT 'Expanded: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE (LN_STAT_CD)',
    delinquency_days    INT             NOT NULL    DEFAULT 0 COMMENT 'Days delinquent (LN_DLQ_DAYS)',

    -- Escrow and LTV
    escrow_balance      DECIMAL(10,2)               COMMENT 'Escrow balance (LN_ESCROW_BAL)',
    ltv_percent         DECIMAL(5,2)                COMMENT 'Loan-to-value percentage (LN_LTV_PCT)',

    -- Property details
    property_address    STRING                      COMMENT 'Property street address (PROP_ADDR_LN1)',
    property_city       STRING                      COMMENT 'PROP_CTY_NM',
    property_state      STRING                      COMMENT 'Two-letter state code (PROP_ST_CD)',
    property_zip        STRING                      COMMENT 'PROP_ZIP_CD',
    property_type       STRING                      COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse (PROP_TYP_CD)',
    appraised_value     DECIMAL(12,2)               COMMENT 'Property appraised value (PROP_APRS_VAL)',

    -- Audit timestamps
    created_at          TIMESTAMP       NOT NULL    COMMENT 'LN_CRET_DT parsed to timestamp',
    updated_at          TIMESTAMP       NOT NULL    COMMENT 'LN_UPDT_DT parsed to timestamp',

    -- Ingestion metadata
    _legacy_source      STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source table for lineage',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields dropped in favor of FK. Partitioned by status for query optimization.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
