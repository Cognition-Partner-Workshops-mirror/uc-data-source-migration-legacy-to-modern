-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from CDW_LN_ACCT
-- are dropped; borrower data is referenced via borrower_key FK to borrowers.
-- Partitioned by status for common filtering on active/closed/default loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_key        BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number          STRING          NOT NULL,
    borrower_key            BIGINT          NOT NULL,
    product_key             BIGINT          NOT NULL,
    original_amount         DECIMAL(12, 2)  NOT NULL,
    current_balance         DECIMAL(12, 2)  NOT NULL,
    interest_rate           DECIMAL(5, 3)   NOT NULL,
    term_months             INT             NOT NULL,
    monthly_payment         DECIMAL(10, 2)  NOT NULL,
    origination_date        DATE            NOT NULL,
    maturity_date           DATE            NOT NULL,
    first_payment_date      DATE,
    next_payment_date       DATE,
    status                  STRING          DEFAULT 'ACTIVE',
    delinquency_days        INT             DEFAULT 0,
    escrow_balance          DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent             DECIMAL(5, 2),
    property_address        STRING,
    property_city           STRING,
    property_state          STRING,
    property_zip            STRING,
    property_type           STRING,
    appraised_value         DECIMAL(12, 2),
    origination_year        INT,
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP,
    _ingestion_ts           TIMESTAMP       DEFAULT current_timestamp(),
    _source_system          STRING          DEFAULT 'CDW_LN_ACCT'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite'       = 'true',
    'delta.autoOptimize.autoCompact'         = 'true',
    'quality.constraints.account_number'     = 'account_number IS NOT NULL',
    'quality.constraints.borrower_key'       = 'borrower_key IS NOT NULL',
    'quality.constraints.product_key'        = 'product_key IS NOT NULL',
    'quality.constraints.original_amount'    = 'original_amount IS NOT NULL',
    'quality.constraints.current_balance'    = 'current_balance IS NOT NULL'
);

ALTER TABLE loan_warehouse.loan_accounts
    SET TBLPROPERTIES ('delta.dataSkippingNumIndexedCols' = '12');
