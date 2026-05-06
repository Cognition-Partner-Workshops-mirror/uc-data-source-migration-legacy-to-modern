-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts - denormalized)
-- =============================================================================
-- Normalized loan accounts with FK references to borrowers and loan_products.
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are
-- dropped in favor of the borrower_id foreign key.
-- Partitioned by status for query optimization on active/closed/default segments.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number      STRING NOT NULL COMMENT 'Legacy LN_ACCT_NBR (e.g., LN-2019-00142)',
    borrower_id         BIGINT NOT NULL COMMENT 'FK to borrowers.id resolved from BORR_ID',
    product_id          BIGINT NOT NULL COMMENT 'FK to loan_products.id resolved from PROD_CD',
    original_amount     DECIMAL(12, 2) NOT NULL COMMENT 'Parsed from comma-formatted string',
    current_balance     DECIMAL(12, 2) NOT NULL COMMENT 'Parsed from comma-formatted string',
    interest_rate       DECIMAL(5, 3) NOT NULL COMMENT 'Parsed from string (e.g., "5.250")',
    term_months         INT NOT NULL COMMENT 'Parsed from VARCHAR string',
    monthly_payment     DECIMAL(10, 2) NOT NULL COMMENT 'Parsed from comma-formatted string',
    origination_date    DATE NOT NULL COMMENT 'Parsed from MM/DD/YYYY string',
    maturity_date       DATE NOT NULL COMMENT 'Parsed from MM/DD/YYYY string',
    first_payment_date  DATE COMMENT 'Parsed from MM/DD/YYYY string',
    next_payment_date   DATE COMMENT 'Parsed from MM/DD/YYYY string',
    status              STRING NOT NULL COMMENT 'Expanded: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE',
    delinquency_days    INT DEFAULT 0 COMMENT 'Parsed from VARCHAR string',
    escrow_balance      DECIMAL(10, 2) COMMENT 'Parsed from comma-formatted string',
    ltv_percent         DECIMAL(5, 2) COMMENT 'Loan-to-value ratio parsed from string',
    property_address    STRING,
    property_city       STRING,
    property_state      STRING COMMENT 'Two-letter state code',
    property_zip        STRING,
    property_type       STRING COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2) COMMENT 'Parsed from comma-formatted string',
    origination_year    INT COMMENT 'Derived from origination_date for partitioning',
    created_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    _migration_source   STRING DEFAULT 'CDW_LN_ACCT' COMMENT 'Lineage tracking',
    _migrated_at        TIMESTAMP DEFAULT current_timestamp() COMMENT 'Migration timestamp'
)
USING DELTA
PARTITIONED BY (status, origination_year)
COMMENT 'Loan accounts migrated from legacy CDW_LN_ACCT with denormalized fields removed'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'quality.constraints.account_number_not_null' = 'account_number IS NOT NULL',
    'quality.constraints.balance_non_negative' = 'current_balance >= 0',
    'quality.constraints.rate_positive' = 'interest_rate > 0'
);
