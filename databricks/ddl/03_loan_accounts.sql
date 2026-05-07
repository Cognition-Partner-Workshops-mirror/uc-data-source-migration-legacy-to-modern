-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from the legacy
-- table are dropped; a borrower_external_id FK is used instead.
-- Partitioned by origination_year (derived from origination_date) for
-- time-based query optimization on loan vintage analysis.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number          STRING          NOT NULL,
    borrower_external_id    STRING          NOT NULL,
    product_code            STRING          NOT NULL,
    original_amount         DECIMAL(12, 2)  NOT NULL,
    current_balance         DECIMAL(12, 2)  NOT NULL,
    interest_rate           DECIMAL(5, 3)   NOT NULL,
    term_months             INT             NOT NULL,
    monthly_payment         DECIMAL(10, 2)  NOT NULL,
    origination_date        DATE            NOT NULL,
    maturity_date           DATE            NOT NULL,
    first_payment_date      DATE,
    next_payment_date       DATE,
    status                  STRING          NOT NULL DEFAULT 'ACTIVE',
    delinquency_days        INT             DEFAULT 0,
    escrow_balance          DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent             DECIMAL(5, 2),
    property_address        STRING,
    property_city           STRING,
    property_state          STRING,
    property_zip            STRING,
    property_type           STRING,
    appraised_value         DECIMAL(12, 2),
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP,
    origination_year        INT             NOT NULL,
    _migration_source       STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at            TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Partitioned by origination_year for vintage analysis. Denormalized borrower fields removed; use borrower_external_id to join to borrowers.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_not_null EXPECT (account_number IS NOT NULL);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_status_valid EXPECT (status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE'));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_property_type_valid EXPECT (property_type IS NULL OR property_type IN ('Single Family', 'Condominium', 'Multi-Family', 'Townhouse'));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_balance_nonneg EXPECT (current_balance >= 0);
