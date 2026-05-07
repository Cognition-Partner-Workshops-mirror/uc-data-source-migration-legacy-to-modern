-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (legacy)
-- =============================================================================
-- Fact table for loan accounts. Normalized: borrower fields removed (use FK to
-- borrowers table). Partitioned by status for common filtering patterns
-- (active vs closed vs default queries).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.borrower_id',
    product_id          BIGINT          NOT NULL    COMMENT 'FK to loan_products.product_id',
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL DEFAULT 'Active',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING          COMMENT 'Single Family, Condominium, Multi-Family, Townhouse',
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    origination_year    INT             COMMENT 'Derived partition column from origination_date',
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed.'
PARTITIONED BY (status, origination_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.expectation.account_number' = 'account_number IS NOT NULL',
    'quality.expectation.borrower_id'    = 'borrower_id IS NOT NULL',
    'quality.expectation.product_id'     = 'product_id IS NOT NULL'
);

-- Z-ORDER recommendation (run post-load):
-- OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_id);
