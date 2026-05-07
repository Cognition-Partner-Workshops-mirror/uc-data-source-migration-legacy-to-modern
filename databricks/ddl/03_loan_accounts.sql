-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Normalizes the denormalized legacy loan account table by:
--   - Dropping redundant borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
--   - Converting borrower_id and product_id to FK references via surrogate keys
--   - Expanding status codes and property type codes to readable values
--   - Parsing all VARCHAR amounts/rates/dates to proper types
-- Partitioned by status for common filtering (active vs closed portfolio queries).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    -- Legacy account number preserved for traceability
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR from CDW_LN_ACCT',
    -- FK to borrowers dimension (replaces denormalized borrower fields)
    borrower_id         BIGINT          NOT NULL COMMENT 'FK to borrowers.id; resolved from legacy BORR_ID via external_id lookup',
    -- FK to loan_products dimension (replaces raw product code)
    product_id          BIGINT          NOT NULL COMMENT 'FK to loan_products.id; resolved from legacy PROD_CD via code lookup',
    -- Financial fields parsed from VARCHAR to proper numeric types
    original_amount     DECIMAL(12,2)   NOT NULL COMMENT 'Original loan amount (was LN_ORIG_AMT)',
    current_balance     DECIMAL(12,2)   NOT NULL COMMENT 'Current outstanding balance (was LN_CURR_BAL)',
    interest_rate       DECIMAL(5,3)    NOT NULL COMMENT 'Interest rate as decimal e.g. 4.750 (was LN_INT_RT)',
    term_months         INT             NOT NULL COMMENT 'Loan term in months (was LN_TERM_MOS)',
    monthly_payment     DECIMAL(10,2)   NOT NULL COMMENT 'Monthly payment amount (was LN_PMT_AMT)',
    -- Date fields parsed from MM/DD/YYYY strings
    origination_date    DATE            NOT NULL COMMENT 'Loan origination date (was LN_ORIG_DT)',
    maturity_date       DATE            NOT NULL COMMENT 'Loan maturity date (was LN_MAT_DT)',
    first_payment_date  DATE            COMMENT 'First payment due date (was LN_1ST_PMT_DT)',
    next_payment_date   DATE            COMMENT 'Next payment due date (was LN_NXT_PMT_DT)',
    -- Status expanded from abbreviation
    status              STRING          NOT NULL COMMENT 'Expanded: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE',
    delinquency_days    INT             DEFAULT 0 COMMENT 'Days delinquent parsed from string (was LN_DLQ_DAYS)',
    escrow_balance      DECIMAL(10,2)   COMMENT 'Escrow balance (was LN_ESCROW_BAL)',
    ltv_percent         DECIMAL(5,2)    COMMENT 'Loan-to-value percentage (was LN_LTV_PCT)',
    -- Property fields (kept in loan_accounts; could be extracted to a property dimension later)
    property_address    STRING          COMMENT 'Property street address (was PROP_ADDR_LN1)',
    property_city       STRING          COMMENT 'Property city (was PROP_CTY_NM)',
    property_state      STRING          COMMENT 'Property two-letter state (was PROP_ST_CD)',
    property_zip        STRING          COMMENT 'Property ZIP code (was PROP_ZIP_CD)',
    property_type       STRING          COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12,2)   COMMENT 'Property appraised value (was PROP_APRS_VAL)',
    -- Audit timestamps
    created_at          TIMESTAMP       COMMENT 'Record creation (was LN_CRET_DT)',
    updated_at          TIMESTAMP       COMMENT 'Last update (was LN_UPDT_DT)',
    -- Pipeline metadata
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Normalized loan accounts migrated from CDW_LN_ACCT. Denormalized borrower fields dropped in favor of borrower_id FK. Partitioned by status for portfolio segmentation queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
