-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.loan_accounts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number      STRING NOT NULL,
    borrower_id         BIGINT NOT NULL,
    product_id          BIGINT NOT NULL,
    original_amount     DECIMAL(12, 2) NOT NULL,
    current_balance     DECIMAL(12, 2) NOT NULL,
    interest_rate       DECIMAL(5, 3) NOT NULL,
    term_months         INT NOT NULL,
    monthly_payment     DECIMAL(10, 2) NOT NULL,
    origination_date    DATE NOT NULL,
    maturity_date       DATE NOT NULL,
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

    CONSTRAINT pk_loan_accounts PRIMARY KEY (id),
    CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_management.borrowers(id),
    CONSTRAINT fk_loan_product FOREIGN KEY (product_id) REFERENCES loan_management.loan_products(id)
)
USING DELTA
COMMENT 'Loan accounts fact table migrated from CDW_LN_ACCT. Denormalized borrower fields removed; use borrower_id FK.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
PARTITIONED BY (status);
