-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts.  Denormalized borrower columns from the
-- legacy table are dropped; a borrower_id FK points to the borrowers table.
-- Partitioned by origination_year (derived from origination_date) to optimise
-- range queries common in loan analytics.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    account_number      STRING        NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT        NOT NULL COMMENT 'FK to borrowers.id resolved via external_id',
    product_id          BIGINT        NOT NULL COMMENT 'FK to loan_products.id resolved via code',
    original_amount     DECIMAL(12,2) COMMENT 'Parsed from comma-formatted string',
    current_balance     DECIMAL(12,2) COMMENT 'Parsed from comma-formatted string',
    interest_rate       DECIMAL(5,3)  COMMENT 'e.g. 4.750',
    term_months         INT           COMMENT 'Parsed from string',
    monthly_payment     DECIMAL(10,2) COMMENT 'Parsed from comma-formatted string',
    origination_date    DATE          COMMENT 'Parsed from MM/DD/YYYY',
    maturity_date       DATE          COMMENT 'Parsed from MM/DD/YYYY',
    first_payment_date  DATE          COMMENT 'Parsed from MM/DD/YYYY',
    next_payment_date   DATE          COMMENT 'Parsed from MM/DD/YYYY',
    status              STRING        COMMENT 'Expanded: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT           COMMENT 'Parsed from string',
    escrow_balance      DECIMAL(10,2) COMMENT 'Parsed from comma-formatted string',
    ltv_percent         DECIMAL(5,2)  COMMENT 'Loan-to-value ratio',
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING        COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12,2) COMMENT 'Parsed from comma-formatted string',
    created_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY',
    origination_year    INT           COMMENT 'Derived partition column: year(origination_date)',
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT pk_loan_accounts PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Modern loan accounts fact table migrated from CDW_LN_ACCT'
PARTITIONED BY (origination_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
