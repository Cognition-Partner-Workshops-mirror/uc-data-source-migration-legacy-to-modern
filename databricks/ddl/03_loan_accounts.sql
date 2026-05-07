-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Core fact table for loan accounts. Normalized: borrower fields removed,
-- replaced by borrower_id FK. Product code replaced by product_id FK.
-- Partitioned by status for efficient querying of active/closed/default loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
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
    status              STRING DEFAULT 'ACTIVE',
    delinquency_days    INT DEFAULT 0,
    escrow_balance      DECIMAL(10, 2) DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP DEFAULT current_timestamp(),
    updated_at          TIMESTAMP DEFAULT current_timestamp(),

    CONSTRAINT loan_accounts_pk PRIMARY KEY (id),
    CONSTRAINT loan_accounts_number_uq UNIQUE (account_number),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT loan_accounts_product_fk FOREIGN KEY (product_id) REFERENCES loan_warehouse.loan_products(id),
    CONSTRAINT loan_accounts_status_values CHECK (status IN ('ACTIVE', 'CLOSED', 'DEFAULT', 'FORBEARANCE')),
    CONSTRAINT loan_accounts_property_type_values CHECK (property_type IS NULL OR property_type IN ('Single Family', 'Condominium', 'Multi-Family', 'Townhouse')),
    CONSTRAINT loan_accounts_orig_amt_pos CHECK (original_amount > 0),
    CONSTRAINT loan_accounts_rate_pos CHECK (interest_rate >= 0),
    CONSTRAINT loan_accounts_term_pos CHECK (term_months > 0),
    CONSTRAINT loan_accounts_dlq_pos CHECK (delinquency_days >= 0),
    CONSTRAINT loan_accounts_ltv_range CHECK (ltv_percent IS NULL OR (ltv_percent >= 0 AND ltv_percent <= 200))
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
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Normalized: denormalized borrower fields removed, FK references to borrowers and loan_products tables added.';
