-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Core fact table for loan accounts. Normalized — borrower info accessed via FK
-- to borrowers table (denormalized borrower fields from legacy are dropped).
-- Partitioned by status for efficient filtering on active/closed/default loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Primary key (auto-generated surrogate key)
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Loan account number (CDW_LN_ACCT.LN_ACCT_NBR)
    account_number      STRING NOT NULL,

    -- Foreign key to borrowers table (resolved from BORR_ID → borrowers.id)
    borrower_id         BIGINT NOT NULL,

    -- Foreign key to loan_products table (resolved from PROD_CD → loan_products.id)
    product_id          BIGINT NOT NULL,

    -- Loan financial details (parsed from comma-formatted VARCHAR strings)
    original_amount     DECIMAL(12, 2) NOT NULL,
    current_balance     DECIMAL(12, 2) NOT NULL,
    interest_rate       DECIMAL(5, 3) NOT NULL,
    term_months         INT NOT NULL,
    monthly_payment     DECIMAL(10, 2) NOT NULL,

    -- Key dates (parsed from MM/DD/YYYY strings)
    origination_date    DATE NOT NULL,
    maturity_date       DATE NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,

    -- Loan status (expanded: ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance)
    status              STRING DEFAULT 'Active',

    -- Delinquency tracking
    delinquency_days    INT DEFAULT 0,

    -- Escrow and valuation (parsed from VARCHAR strings)
    escrow_balance      DECIMAL(10, 2) DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),

    -- Property details
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12, 2),

    -- Audit timestamps
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Constraints
    CONSTRAINT pk_loan_accounts PRIMARY KEY (id),
    CONSTRAINT uq_loan_accounts_number UNIQUE (account_number),
    CONSTRAINT fk_loan_accounts_borrower FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT fk_loan_accounts_product FOREIGN KEY (product_id) REFERENCES loan_warehouse.loan_products(id)
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
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Normalized structure with FK references to borrowers and loan_products. Denormalized borrower fields removed.';
