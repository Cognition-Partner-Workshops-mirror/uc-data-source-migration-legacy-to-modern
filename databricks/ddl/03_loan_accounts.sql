-- =============================================================================
-- Delta Lake Table: loan_accounts (fact table)
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Migrated from the legacy CDW_LN_ACCT table. Key changes:
--   - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
--     are dropped; the borrower_id FK references borrowers.id instead.
--   - PROD_CD is resolved to a surrogate product_id referencing loan_products.id.
--   - All VARCHAR amounts/rates are parsed to DECIMAL.
--   - Status codes expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE.
--   - Property type codes expanded: SFR→Single Family, CND→Condominium, etc.
--   - Partitioned by loan status for query performance on active-vs-closed analytics.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy LN_ACCT_NBR preserved as natural key (legacy: LN_ACCT_NBR)
    account_number      STRING          NOT NULL
        COMMENT 'Legacy loan account number from CDW_LN_ACCT',

    -- FK to borrowers table, resolved from legacy BORR_ID via borrowers.external_id lookup
    borrower_id         BIGINT          NOT NULL
        COMMENT 'FK to borrowers.id; resolved from legacy BORR_ID',

    -- FK to loan_products table, resolved from legacy PROD_CD via loan_products.code lookup
    product_id          BIGINT          NOT NULL
        COMMENT 'FK to loan_products.id; resolved from legacy PROD_CD',

    -- Financial fields parsed from comma-formatted VARCHAR strings
    original_amount     DECIMAL(12, 2)  NOT NULL
        COMMENT 'Original loan amount, parsed from legacy LN_ORIG_AMT',
    current_balance     DECIMAL(12, 2)  NOT NULL
        COMMENT 'Current loan balance, parsed from legacy LN_CURR_BAL',
    interest_rate       DECIMAL(5, 3)   NOT NULL
        COMMENT 'Interest rate, parsed from legacy LN_INT_RT',
    term_months         INT             NOT NULL
        COMMENT 'Loan term in months, parsed from legacy LN_TERM_MOS',
    monthly_payment     DECIMAL(10, 2)  NOT NULL
        COMMENT 'Monthly payment amount, parsed from legacy LN_PMT_AMT',

    -- Date fields parsed from MM/DD/YYYY strings
    origination_date    DATE            NOT NULL
        COMMENT 'Loan origination date, parsed from legacy LN_ORIG_DT',
    maturity_date       DATE            NOT NULL
        COMMENT 'Loan maturity date, parsed from legacy LN_MAT_DT',
    first_payment_date  DATE
        COMMENT 'First payment date, parsed from legacy LN_1ST_PMT_DT',
    next_payment_date   DATE
        COMMENT 'Next scheduled payment date, parsed from legacy LN_NXT_PMT_DT',

    -- Expanded from abbreviation (legacy: LN_STAT_CD)
    -- ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
    status              STRING          DEFAULT 'ACTIVE'
        COMMENT 'Loan status: ACTIVE, CLOSED, DEFAULT, or FORBEARANCE',

    -- Parsed from VARCHAR (legacy: LN_DLQ_DAYS)
    delinquency_days    INT             DEFAULT 0
        COMMENT 'Number of days delinquent, parsed from legacy VARCHAR',

    -- Parsed from comma-formatted VARCHAR (legacy: LN_ESCROW_BAL)
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0
        COMMENT 'Escrow balance, parsed from legacy LN_ESCROW_BAL',

    -- Parsed from VARCHAR (legacy: LN_LTV_PCT)
    ltv_percent         DECIMAL(5, 2)
        COMMENT 'Loan-to-value percentage, parsed from legacy VARCHAR',

    -- Property fields (legacy: PROP_ADDR_LN1, PROP_CTY_NM, PROP_ST_CD, PROP_ZIP_CD)
    property_address    STRING,
    property_city       STRING,
    property_state      STRING          COMMENT 'Two-letter state code',
    property_zip        STRING,

    -- Expanded from code (SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse)
    property_type       STRING
        COMMENT 'Property type, expanded from legacy PROP_TYP_CD code',

    -- Parsed from comma-formatted VARCHAR (legacy: PROP_APRS_VAL)
    appraised_value     DECIMAL(12, 2)
        COMMENT 'Appraised property value, parsed from legacy VARCHAR',

    -- Parsed from MM/DD/YYYY strings
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Audit column
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
        COMMENT 'Timestamp when the row was loaded by the migration pipeline'
)
USING DELTA
-- Partition by status for efficient filtering on active-vs-closed loan analytics
PARTITIONED BY (status)
COMMENT 'Modern loan accounts fact table migrated from legacy CDW_LN_ACCT. Partitioned by loan status.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on account number
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_unique UNIQUE (account_number);
