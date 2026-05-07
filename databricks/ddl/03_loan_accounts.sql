-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from the legacy
-- table are dropped; a foreign key to borrowers replaces them.
-- Partitioned by status to optimise the most common query pattern
-- (active-loan dashboards, default-monitoring, closed-loan archival).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT          NOT NULL COMMENT 'FK → borrowers.borrower_id (resolved from BORR_ID)',
    product_id          BIGINT          NOT NULL COMMENT 'FK → loan_products.product_id (resolved from PROD_CD)',
    original_amount     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_ORIG_AMT — parsed, commas removed',
    current_balance     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_CURR_BAL — parsed, commas removed',
    interest_rate       DECIMAL(5, 3)   NOT NULL COMMENT 'Legacy LN_INT_RT — parsed from string',
    term_months         INT             NOT NULL COMMENT 'Legacy LN_TERM_MOS — parsed from string',
    monthly_payment     DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy LN_PMT_AMT — parsed, commas removed',
    origination_date    DATE            NOT NULL COMMENT 'Legacy LN_ORIG_DT — parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL COMMENT 'Legacy LN_MAT_DT — parsed from MM/DD/YYYY',
    first_payment_date  DATE            COMMENT 'Legacy LN_1ST_PMT_DT — parsed from MM/DD/YYYY',
    next_payment_date   DATE            COMMENT 'Legacy LN_NXT_PMT_DT — parsed from MM/DD/YYYY',
    status              STRING          NOT NULL DEFAULT 'Active' COMMENT 'Legacy LN_STAT_CD expanded: ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance',
    delinquency_days    INT             DEFAULT 0 COMMENT 'Legacy LN_DLQ_DAYS — parsed from string',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0 COMMENT 'Legacy LN_ESCROW_BAL — parsed, commas removed',
    ltv_percent         DECIMAL(5, 2)   COMMENT 'Legacy LN_LTV_PCT — parsed from string',
    property_address    STRING          COMMENT 'Legacy PROP_ADDR_LN1',
    property_city       STRING          COMMENT 'Legacy PROP_CTY_NM',
    property_state      STRING          COMMENT 'Legacy PROP_ST_CD',
    property_zip        STRING          COMMENT 'Legacy PROP_ZIP_CD',
    property_type       STRING          COMMENT 'Legacy PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)  COMMENT 'Legacy PROP_APRS_VAL — parsed, commas removed',
    origination_year    INT             COMMENT 'Derived from origination_date for partitioning',
    created_at          TIMESTAMP       COMMENT 'Legacy LN_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy LN_UPDT_DT — parsed from MM/DD/YYYY',
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Lineage: source table',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Lineage: ingestion timestamp',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (loan_account_id),
    CONSTRAINT loan_accounts_number_uq UNIQUE (account_number),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers (borrower_id),
    CONSTRAINT loan_accounts_product_fk  FOREIGN KEY (product_id)  REFERENCES loan_warehouse.loan_products (product_id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table — migrated from CDW_LN_ACCT. Denormalized borrower columns dropped in favour of FK.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
