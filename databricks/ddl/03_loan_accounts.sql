-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Core Data Warehouse)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are dropped; use
-- the borrower_id foreign key to join to the borrowers dimension.
-- Partitioned by status to accelerate portfolio segmentation queries
-- (active vs closed vs default).
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
    property_type       STRING          COMMENT 'Single Family, Condominium, Multi-Family, Townhouse',
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _load_ts            TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_LN_ACCT',

    CONSTRAINT pk_loan_accounts PRIMARY KEY (loan_account_id),
    CONSTRAINT uq_loan_accounts_num UNIQUE (account_number),
    CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(borrower_id),
    CONSTRAINT fk_loan_product FOREIGN KEY (product_id) REFERENCES loan_warehouse.loan_products(product_id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from CDW_LN_ACCT. Partitioned by loan status for portfolio segmentation.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);
