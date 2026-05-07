-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy CDW Loan Accounts)
-- =============================================================================
-- Normalized loan account fact table. Denormalized borrower columns from the
-- legacy CDW_LN_ACCT table are dropped; borrower data is referenced via
-- borrower_id FK to the borrowers table.
--
-- Partitioned by origination_year (extracted from origination_date) to support
-- vintage analysis, cohort reporting, and efficient time-range queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL,
    product_id          BIGINT          NOT NULL,
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
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    origination_year    INT             GENERATED ALWAYS AS (YEAR(origination_date)),
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower columns dropped. Partitioned by origination year for vintage cohort analysis.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_account_number_unique UNIQUE (account_number);
