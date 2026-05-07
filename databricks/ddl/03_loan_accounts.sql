-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields are removed;
-- borrower data is referenced via borrower_id FK to borrowers table.
-- Partitioned by status for efficient filtering of active vs. closed loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL,
    product_code        STRING          NOT NULL,
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL DEFAULT 'ACTIVE',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12, 2),
    origination_year    INT             GENERATED ALWAYS AS (year(origination_date)),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table migrated from CDW_LN_ACCT. Denormalized borrower fields removed.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_not_null EXPECT (account_number IS NOT NULL);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_balance_non_negative
    EXPECT (current_balance >= 0);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_rate_range
    EXPECT (interest_rate >= 0 AND interest_rate <= 100);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_status_valid
    EXPECT (status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE'));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_ltv_range
    EXPECT (ltv_percent IS NULL OR (ltv_percent >= 0 AND ltv_percent <= 200));
