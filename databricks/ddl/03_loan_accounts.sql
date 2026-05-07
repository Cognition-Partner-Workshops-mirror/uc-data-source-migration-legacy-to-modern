-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Normalized: borrower and product
-- fields are now foreign keys. Partitioned by status for common queries
-- (active vs. closed portfolio analysis).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number      STRING NOT NULL,
    borrower_id         BIGINT NOT NULL,
    product_id          BIGINT NOT NULL,
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
    _ingestion_ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    _source_system      STRING DEFAULT 'CDW_LN_ACCT'
)
USING DELTA
PARTITIONED BY (status)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; uses FK to borrowers. Partitioned by loan status.';

-- Constraints
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_pk PRIMARY KEY (id);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_borrower_fk
    FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers (id);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_product_fk
    FOREIGN KEY (product_id) REFERENCES loan_warehouse.loan_products (id);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_balance_nonneg
    CHECK (current_balance IS NULL OR current_balance >= 0);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_status_valid
    CHECK (status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE'));
