-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower columns from the
-- legacy table are dropped in favor of a foreign key to the borrowers table.
-- Partitioned by status to optimize the most common query pattern: filtering
-- active vs. closed/defaulted loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT          COMMENT 'FK to borrowers.id; NOT NULL enforced by quality checks',
    product_id          BIGINT          COMMENT 'FK to loan_products.id; NOT NULL enforced by quality checks',
    original_amount     DECIMAL(12, 2),
    current_balance     DECIMAL(12, 2),
    interest_rate       DECIMAL(5, 3),
    term_months         INT,
    monthly_payment     DECIMAL(10, 2),
    origination_date    DATE,
    maturity_date       DATE,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL COMMENT 'ACTIVE, CLOSED, DEFAULT, FORBEARANCE',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2),
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING          COMMENT 'Single Family, Condominium, Multi-Family, Townhouse',
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    origination_year    INT             COMMENT 'Derived from origination_date for partitioning',
    _migration_src      STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source table for lineage',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Migration run timestamp',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (id),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT loan_accounts_product_fk  FOREIGN KEY (product_id)  REFERENCES loan_warehouse.loan_products(id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table migrated from CDW_LN_ACCT'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
