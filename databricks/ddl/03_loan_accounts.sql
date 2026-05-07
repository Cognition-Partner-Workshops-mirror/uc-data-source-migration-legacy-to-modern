-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (legacy)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from the legacy
-- table are dropped; references are via borrower_key FK.
-- Partitioned by origination_year (derived from origination_date) for
-- time-series query performance on loan portfolios.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_key    BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR (e.g. LN-2019-00142)',
    borrower_key        BIGINT          NOT NULL COMMENT 'FK → borrowers.borrower_key (resolved from BORR_ID)',
    product_key         BIGINT          NOT NULL COMMENT 'FK → loan_products.product_key (resolved from PROD_CD)',
    original_amount     DECIMAL(12, 2)  NOT NULL COMMENT 'Parsed from LN_ORIG_AMT (remove commas)',
    current_balance     DECIMAL(12, 2)  NOT NULL COMMENT 'Parsed from LN_CURR_BAL (remove commas)',
    interest_rate       DECIMAL(5, 3)   NOT NULL COMMENT 'Parsed from LN_INT_RT (string to decimal)',
    term_months         INT             NOT NULL COMMENT 'Parsed from LN_TERM_MOS (string to int)',
    monthly_payment     DECIMAL(10, 2)  NOT NULL COMMENT 'Parsed from LN_PMT_AMT (remove commas)',
    origination_date    DATE            NOT NULL COMMENT 'Parsed from LN_ORIG_DT (MM/DD/YYYY)',
    maturity_date       DATE            NOT NULL COMMENT 'Parsed from LN_MAT_DT (MM/DD/YYYY)',
    first_payment_date  DATE            COMMENT 'Parsed from LN_1ST_PMT_DT (MM/DD/YYYY)',
    next_payment_date   DATE            COMMENT 'Parsed from LN_NXT_PMT_DT (MM/DD/YYYY)',
    status              STRING          NOT NULL DEFAULT 'Active' COMMENT 'Expanded from LN_STAT_CD: ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance',
    delinquency_days    INT             DEFAULT 0 COMMENT 'Parsed from LN_DLQ_DAYS (string to int)',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0 COMMENT 'Parsed from LN_ESCROW_BAL (remove commas)',
    ltv_percent         DECIMAL(5, 2)   COMMENT 'Parsed from LN_LTV_PCT (string to decimal)',
    property_address    STRING          COMMENT 'Mapped from PROP_ADDR_LN1',
    property_city       STRING          COMMENT 'Mapped from PROP_CTY_NM',
    property_state      STRING          COMMENT 'Mapped from PROP_ST_CD',
    property_zip        STRING          COMMENT 'Mapped from PROP_ZIP_CD',
    property_type       STRING          COMMENT 'Expanded from PROP_TYP_CD: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)  COMMENT 'Parsed from PROP_APRS_VAL (remove commas)',
    created_at          TIMESTAMP       COMMENT 'Parsed from LN_CRET_DT (MM/DD/YYYY)',
    updated_at          TIMESTAMP       COMMENT 'Parsed from LN_UPDT_DT (MM/DD/YYYY)',
    origination_year    INT             NOT NULL COMMENT 'Derived from origination_date for partitioning',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration load',
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source table identifier',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (loan_account_key),
    CONSTRAINT loan_accounts_number_uq UNIQUE (account_number),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_key) REFERENCES loan_warehouse.borrowers (borrower_key),
    CONSTRAINT loan_accounts_product_fk FOREIGN KEY (product_key) REFERENCES loan_warehouse.loan_products (product_key)
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan accounts fact table — migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; use borrower_key FK.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
