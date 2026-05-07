-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from
-- CDW_LN_ACCT are dropped; borrower_external_id provides the FK link.
-- Partitioned by status for common query patterns (active vs closed loans).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number          STRING          NOT NULL,
    borrower_external_id    STRING          NOT NULL,
    product_code            STRING          NOT NULL,
    original_amount         DECIMAL(12, 2)  NOT NULL,
    current_balance         DECIMAL(12, 2)  NOT NULL,
    interest_rate           DECIMAL(5, 3)   NOT NULL,
    term_months             INT             NOT NULL,
    monthly_payment         DECIMAL(10, 2)  NOT NULL,
    origination_date        DATE            NOT NULL,
    maturity_date           DATE            NOT NULL,
    first_payment_date      DATE,
    next_payment_date       DATE,
    status                  STRING          NOT NULL DEFAULT 'ACTIVE',
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
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Partitioned by status for active/closed segmentation.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_accounts
ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);
