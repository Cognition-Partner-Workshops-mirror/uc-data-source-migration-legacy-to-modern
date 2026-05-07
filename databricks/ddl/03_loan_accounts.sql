-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from CDW_LN_ACCT
-- are dropped; a foreign-key-style reference to borrowers is used instead.
-- Partitioned by status for efficient filtering of active vs. closed loans.
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
    status              STRING          NOT NULL DEFAULT 'Active'
                                        COMMENT 'Active, Closed, Default, Forbearance',
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
    origination_year    INT             GENERATED ALWAYS AS (YEAR(origination_date))
                                        COMMENT 'Derived partition column',
    _legacy_ln_acct_nbr STRING          COMMENT 'Original CDW_LN_ACCT.LN_ACCT_NBR for lineage',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp'
)
USING DELTA
COMMENT 'Loan account fact table migrated from CDW_LN_ACCT'
PARTITIONED BY (status, origination_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);
