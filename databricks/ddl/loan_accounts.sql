-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table are dropped; borrower_id references the borrowers dimension.
-- Partitioned by status for efficient filtering on active/closed/default loans.
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
    origination_year    INT             NOT NULL,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status, origination_year)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Partitioned by status and origination_year for portfolio analysis and servicing queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);

-- Foreign key constraints (informational in Databricks, not enforced at write time)
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id)
    REFERENCES loan_warehouse.borrowers (borrower_id);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT fk_loan_product FOREIGN KEY (product_id)
    REFERENCES loan_warehouse.loan_products (product_id);

-- Z-ORDER recommendation for common access patterns:
-- OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_id, origination_date);
