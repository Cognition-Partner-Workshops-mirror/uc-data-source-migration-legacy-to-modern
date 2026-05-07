-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy CDW)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from
-- CDW_LN_ACCT are dropped; borrower data is referenced via borrower_id FK.
-- Partitioned by status for common analytical query patterns (active vs closed).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_key            BIGINT GENERATED ALWAYS AS IDENTITY,
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
    status              STRING          DEFAULT 'ACTIVE',
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
    origination_year    INT GENERATED ALWAYS AS (YEAR(origination_date)),
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed. Partitioned by status for portfolio analytics.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);

-- Constraints
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_unique UNIQUE (account_number);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_status_valid
    CHECK (status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE'));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_property_type_valid
    CHECK (property_type IS NULL OR property_type IN (
        'Single Family', 'Condominium', 'Multi-Family', 'Townhouse'
    ));

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_balance_positive
    CHECK (current_balance >= 0);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_rate_positive
    CHECK (interest_rate > 0);
