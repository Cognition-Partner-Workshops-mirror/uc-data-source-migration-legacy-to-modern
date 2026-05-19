-- =============================================================================
-- Delta Lake Table: loan_accounts
-- =============================================================================
-- Source: CDW_LN_ACCT (legacy loan accounts table, denormalized)
--
-- Migration notes:
--   - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
--     are dropped; replaced by borrower_id FK referencing borrowers table
--   - PROD_CD resolved to product_id FK referencing loan_products table
--   - Status codes expanded: ACT -> ACTIVE, CLO -> CLOSED, DFT -> DEFAULT,
--     FRB -> FORBEARANCE
--   - Property type codes expanded: SFR -> Single Family, CND -> Condominium,
--     MFR -> Multi-Family, TWN -> Townhouse
--   - All amount fields parsed from comma-formatted strings to DECIMAL
--   - All date fields parsed from MM/DD/YYYY strings to DATE
--   - Interest rate and LTV parsed from strings to DECIMAL
--   - Partitioned by origination_year (derived from origination_date) for
--     efficient time-range queries on loan portfolios
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.loan_accounts (
    -- Surrogate primary key
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy LN_ACCT_NBR preserved as natural key
    account_number      STRING        NOT NULL,

    -- FK to borrowers table (resolved from legacy BORR_ID via external_id lookup)
    borrower_id         BIGINT        NOT NULL,

    -- FK to loan_products table (resolved from legacy PROD_CD via code lookup)
    product_id          BIGINT        NOT NULL,

    -- Loan amount fields: parsed from comma-formatted strings to DECIMAL
    original_amount     DECIMAL(12, 2) NOT NULL,
    current_balance     DECIMAL(12, 2) NOT NULL,

    -- Interest rate: parsed from string (e.g., "4.750") to DECIMAL
    interest_rate       DECIMAL(5, 3)  NOT NULL,

    -- Term: parsed from string to INT
    term_months         INT            NOT NULL,

    -- Monthly payment: parsed from comma-formatted string to DECIMAL
    monthly_payment     DECIMAL(10, 2) NOT NULL,

    -- Date fields: all parsed from MM/DD/YYYY strings to DATE
    origination_date    DATE           NOT NULL,
    maturity_date       DATE           NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,

    -- Status: expanded from abbreviation (ACT -> ACTIVE, CLO -> CLOSED, etc.)
    status              STRING         DEFAULT 'ACTIVE',

    -- Delinquency days: parsed from string to INT
    delinquency_days    INT            DEFAULT 0,

    -- Escrow balance: parsed from comma-formatted string to DECIMAL
    escrow_balance      DECIMAL(10, 2) DEFAULT 0,

    -- Loan-to-value percentage: parsed from string to DECIMAL
    ltv_percent         DECIMAL(5, 2),

    -- Property fields (direct copy from PROP_* columns)
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,

    -- Property type: expanded from code (SFR -> Single Family, etc.)
    property_type       STRING,

    -- Appraised value: parsed from comma-formatted string to DECIMAL
    appraised_value     DECIMAL(12, 2),

    -- Derived partition column: extracted year from origination_date
    origination_year    INT,

    -- Audit timestamps: parsed from MM/DD/YYYY strings to TIMESTAMP
    created_at          TIMESTAMP      DEFAULT current_timestamp(),
    updated_at          TIMESTAMP      DEFAULT current_timestamp(),

    -- Constraints (informational for Delta Lake, not enforced)
    CONSTRAINT pk_loan_accounts PRIMARY KEY (id),
    CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_management.borrowers(id),
    CONSTRAINT fk_loan_product FOREIGN KEY (product_id) REFERENCES loan_management.loan_products(id)
)
USING DELTA
-- Partition by origination year for efficient portfolio time-range queries
PARTITIONED BY (origination_year)
COMMENT 'Normalized loan accounts table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; uses FK references instead. Partitioned by origination year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);
