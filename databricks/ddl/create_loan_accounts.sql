-- =============================================================================
-- Delta Lake: loan_accounts table
-- Source: CDW_LN_ACCT (legacy, denormalized)
-- =============================================================================
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
-- are dropped. Use borrower_id FK to join to borrowers table instead.

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT          NOT NULL COMMENT 'FK to borrowers.id (resolved from BORR_ID)',
    product_id          BIGINT          NOT NULL COMMENT 'FK to loan_products.id (resolved from PROD_CD)',
    original_amount     DECIMAL(12,2)   NOT NULL COMMENT 'Parsed from comma-formatted string',
    current_balance     DECIMAL(12,2)   NOT NULL,
    interest_rate       DECIMAL(5,3)    NOT NULL COMMENT 'e.g. 4.750',
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10,2)   NOT NULL,
    origination_date    DATE            NOT NULL COMMENT 'Parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL COMMENT 'ACTIVE/CLOSED/DEFAULT/FORBEARANCE',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10,2)   DEFAULT 0.00,
    ltv_percent         DECIMAL(5,2)    COMMENT 'Loan-to-Value ratio',
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING          COMMENT 'Single Family/Condominium/Multi-Family/Townhouse',
    appraised_value     DECIMAL(12,2),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    CONSTRAINT loan_accounts_pk PRIMARY KEY (id),
    CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT fk_loan_product FOREIGN KEY (product_id) REFERENCES loan_warehouse.loan_products(id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan accounts migrated from CDW_LN_ACCT. Partitioned by status for efficient querying of active vs closed loans.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

CREATE INDEX IF NOT EXISTS idx_loan_accounts_number
ON loan_warehouse.loan_accounts (account_number);

CREATE INDEX IF NOT EXISTS idx_loan_accounts_borrower
ON loan_warehouse.loan_accounts (borrower_id);
