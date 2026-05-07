-- =============================================================================
-- Delta Lake Table: loan_accounts (fact table)
-- Source: CDW_LN_ACCT
-- =============================================================================
-- Loan accounts fact table with proper FK references to borrowers and
-- loan_products. Partitioned by origination year for time-based query
-- optimization and data lifecycle management.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number      STRING NOT NULL,
    borrower_id         STRING NOT NULL,
    product_code        STRING NOT NULL,
    original_amount     DECIMAL(12, 2),
    current_balance     DECIMAL(12, 2),
    interest_rate       DECIMAL(5, 3),
    term_months         INT,
    monthly_payment     DECIMAL(10, 2),
    origination_date    DATE,
    maturity_date       DATE,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING NOT NULL,
    delinquency_days    INT DEFAULT 0,
    escrow_balance      DECIMAL(10, 2),
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
    _ingestion_ts       TIMESTAMP DEFAULT current_timestamp(),
    _source_system      STRING DEFAULT 'CDW_LEGACY'
)
USING DELTA
PARTITIONED BY (origination_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; references borrowers via borrower_id. Partitioned by origination_year for time-series analytics.';

-- Constraints
ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);

ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_status_check CHECK (
    status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE')
);

ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_balance_positive CHECK (
    current_balance IS NULL OR current_balance >= 0
);

ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_rate_positive CHECK (
    interest_rate IS NULL OR interest_rate >= 0
);
