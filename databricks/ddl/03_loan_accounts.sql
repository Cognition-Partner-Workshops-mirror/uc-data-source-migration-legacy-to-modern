-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table are dropped; borrower_key references the borrowers dimension.
-- Partitioned by status for efficient filtering on active/closed/default loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_key    BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_key        BIGINT          NOT NULL,
    product_key         BIGINT          NOT NULL,
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          DEFAULT 'Active',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12, 2),
    origination_year    INT GENERATED ALWAYS AS (YEAR(origination_date)),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from CDW_LN_ACCT. Denormalized borrower fields removed.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_status_values
    CHECK (status IN ('Active', 'Closed', 'Default', 'Forbearance'));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_property_type_values
    CHECK (property_type IS NULL OR property_type IN (
        'Single Family', 'Condominium', 'Multi-Family', 'Townhouse'
    ));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_positive_amounts
    CHECK (original_amount > 0 AND monthly_payment > 0);
