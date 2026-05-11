-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are dropped in
-- favour of a foreign key to the borrowers dimension.
--
-- Status codes expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
-- Property type codes expanded: SFR→Single Family, CND→Condominium,
--                                MFR→Multi-Family, TWN→Townhouse
--
-- Partitioned by loan status — most analytical queries filter by status and
-- the cardinality is low (4 values), making it ideal for partition pruning.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    id                  BIGINT         GENERATED ALWAYS AS IDENTITY,

    -- Natural key from legacy system
    account_number      STRING         NOT NULL  COMMENT 'Legacy LN_ACCT_NBR',

    -- Foreign keys (resolved during ingestion via lookup)
    borrower_id         BIGINT         NOT NULL  COMMENT 'FK → borrowers.id (resolved from BORR_ID)',
    product_id          BIGINT         NOT NULL  COMMENT 'FK → loan_products.id (resolved from PROD_CD)',

    -- Loan financials
    original_amount     DECIMAL(12,2)            COMMENT 'Parsed from LN_ORIG_AMT (commas removed)',
    current_balance     DECIMAL(12,2)            COMMENT 'Parsed from LN_CURR_BAL (commas removed)',
    interest_rate       DECIMAL(5,3)             COMMENT 'Parsed from LN_INT_RT string → decimal',
    term_months         INT                      COMMENT 'Parsed from LN_TERM_MOS string → integer',
    monthly_payment     DECIMAL(10,2)            COMMENT 'Parsed from LN_PMT_AMT (commas removed)',

    -- Key dates
    origination_date    DATE                     COMMENT 'Parsed from LN_ORIG_DT (MM/DD/YYYY)',
    maturity_date       DATE                     COMMENT 'Parsed from LN_MAT_DT (MM/DD/YYYY)',
    first_payment_date  DATE                     COMMENT 'Parsed from LN_1ST_PMT_DT (MM/DD/YYYY)',
    next_payment_date   DATE                     COMMENT 'Parsed from LN_NXT_PMT_DT (MM/DD/YYYY)',

    -- Status & delinquency
    status              STRING         NOT NULL  COMMENT 'Expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT                      COMMENT 'Parsed from LN_DLQ_DAYS string → integer',

    -- Escrow & LTV
    escrow_balance      DECIMAL(10,2)            COMMENT 'Parsed from LN_ESCROW_BAL (commas removed)',
    ltv_percent         DECIMAL(5,2)             COMMENT 'Parsed from LN_LTV_PCT string → decimal',

    -- Property details (kept inline — single property per loan)
    property_address    STRING                   COMMENT 'Mapped from PROP_ADDR_LN1',
    property_city       STRING                   COMMENT 'Mapped from PROP_CTY_NM',
    property_state      STRING                   COMMENT 'Mapped from PROP_ST_CD',
    property_zip        STRING                   COMMENT 'Mapped from PROP_ZIP_CD',
    property_type       STRING                   COMMENT 'Expanded: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12,2)            COMMENT 'Parsed from PROP_APRS_VAL (commas removed)',

    -- Audit timestamps
    created_at          TIMESTAMP                COMMENT 'Parsed from LN_CRET_DT (MM/DD/YYYY)',
    updated_at          TIMESTAMP                COMMENT 'Parsed from LN_UPDT_DT (MM/DD/YYYY)',

    -- Delta Lake metadata
    _ingestion_ts       TIMESTAMP    DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system      STRING       DEFAULT 'CDW_LN_ACCT'       COMMENT 'Source system identifier'
)
USING DELTA
-- Partition by status for efficient query pruning on loan lifecycle analytics
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table — migrated from legacy CDW_LN_ACCT (denormalized borrower fields removed)'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on legacy account number
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_nbr_unique UNIQUE (account_number);
