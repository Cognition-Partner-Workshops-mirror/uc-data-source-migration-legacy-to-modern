-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table are dropped; borrower data is referenced via borrower_key FK.
-- Partitioned by status for common filtering patterns (active vs closed loans).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_key    BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_key        BIGINT          NOT NULL COMMENT 'FK to borrowers, resolved from legacy BORR_ID',
    product_key         BIGINT          NOT NULL COMMENT 'FK to loan_products, resolved from legacy PROD_CD',
    original_amount     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_ORIG_AMT parsed from comma-string',
    current_balance     DECIMAL(12, 2)  NOT NULL COMMENT 'Legacy LN_CURR_BAL parsed from comma-string',
    interest_rate       DECIMAL(5, 3)   NOT NULL COMMENT 'Legacy LN_INT_RT parsed from string',
    term_months         INT             NOT NULL COMMENT 'Legacy LN_TERM_MOS parsed from string',
    monthly_payment     DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy LN_PMT_AMT parsed from comma-string',
    origination_date    DATE            NOT NULL COMMENT 'Legacy LN_ORIG_DT parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL COMMENT 'Legacy LN_MAT_DT parsed from MM/DD/YYYY',
    first_payment_date  DATE            COMMENT 'Legacy LN_1ST_PMT_DT parsed from MM/DD/YYYY',
    next_payment_date   DATE            COMMENT 'Legacy LN_NXT_PMT_DT parsed from MM/DD/YYYY',
    status              STRING          NOT NULL DEFAULT 'Active' COMMENT 'Expanded from LN_STAT_CD: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT             DEFAULT 0 COMMENT 'Legacy LN_DLQ_DAYS parsed from string',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0.00 COMMENT 'Legacy LN_ESCROW_BAL parsed from comma-string',
    ltv_percent         DECIMAL(5, 2)   COMMENT 'Legacy LN_LTV_PCT parsed from string',
    property_address    STRING          COMMENT 'Legacy PROP_ADDR_LN1',
    property_city       STRING          COMMENT 'Legacy PROP_CTY_NM',
    property_state      STRING          COMMENT 'Legacy PROP_ST_CD',
    property_zip        STRING          COMMENT 'Legacy PROP_ZIP_CD',
    property_type       STRING          COMMENT 'Expanded from PROP_TYP_CD: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2)  COMMENT 'Legacy PROP_APRS_VAL parsed from comma-string',
    created_at          TIMESTAMP       COMMENT 'Legacy LN_CRET_DT parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy LN_UPDT_DT parsed from MM/DD/YYYY',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (loan_account_key),
    CONSTRAINT loan_accounts_number_uq UNIQUE (account_number),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_key) REFERENCES loan_warehouse.borrowers (borrower_key),
    CONSTRAINT loan_accounts_product_fk FOREIGN KEY (product_key) REFERENCES loan_warehouse.loan_products (product_key)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table migrated from CDW_LN_ACCT. Denormalized borrower fields removed. Partitioned by loan status.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
