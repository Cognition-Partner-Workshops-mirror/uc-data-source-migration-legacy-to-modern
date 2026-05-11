-- =============================================================================
-- Delta Lake Table: loan_accounts
-- =============================================================================
-- Source: CDW_LN_ACCT (legacy denormalized loan account table with embedded
--         borrower fields and all-VARCHAR columns)
-- Target: loan_accounts (modern typed, normalized — borrower fields removed,
--         FK references used instead)
--
-- Key transformations from legacy:
--   - Denormalized BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 dropped; use borrower FK
--   - PROD_CD resolved to product_id via loan_products lookup
--   - BORR_ID resolved to borrower_id via borrowers lookup
--   - LN_ORIG_AMT, LN_CURR_BAL, etc. (VARCHAR with commas) → DECIMAL
--   - LN_STAT_CD (ACT/CLO/DFT/FRB) → status (expanded string)
--   - PROP_TYP_CD (SFR/CND/MFR/TWN) → property_type (expanded string)
--   - All date VARCHARs (MM/DD/YYYY) → DATE or TIMESTAMP
--
-- Partitioning: by origination_year — natural time-based partition for loan data.
--   Queries often filter by origination vintage; year-level partitioning balances
--   partition count vs. data skew for typical loan portfolios.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    -- Surrogate key
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Natural key carried from legacy CDW_LN_ACCT.LN_ACCT_NBR
    account_number      STRING          NOT NULL,

    -- FK to borrowers dimension — resolved from legacy BORR_ID via external_id lookup
    borrower_id         BIGINT          NOT NULL,

    -- FK to loan_products dimension — resolved from legacy PROD_CD via code lookup
    product_id          BIGINT          NOT NULL,

    -- Financial amounts — parsed from legacy comma-formatted VARCHAR to decimal
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,

    -- Loan lifecycle dates — parsed from legacy MM/DD/YYYY VARCHAR
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,

    -- Status — expanded from legacy abbreviation:
    --   ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance
    status              STRING          NOT NULL DEFAULT 'Active',

    -- Delinquency days — parsed from legacy VARCHAR
    delinquency_days    INT             DEFAULT 0,

    -- Escrow balance — parsed from legacy comma-formatted VARCHAR
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0,

    -- Loan-to-value percentage — parsed from legacy VARCHAR
    ltv_percent         DECIMAL(5, 2),

    -- Property details (direct copy from legacy, except property_type which is expanded)
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12, 2),

    -- Audit timestamps — parsed from legacy MM/DD/YYYY strings
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Partition column — derived from origination_date during ingestion
    origination_year    INT             NOT NULL,

    -- ETL metadata columns for lineage tracking
    _etl_loaded_at      TIMESTAMP       DEFAULT current_timestamp(),
    _etl_source         STRING          DEFAULT 'CDW_LN_ACCT'
)
USING DELTA
-- Partition by origination year: natural vintage-based partitioning for loan portfolios.
-- Queries filtering by year range benefit from partition pruning.
PARTITIONED BY (origination_year)
COMMENT 'Modern loan accounts table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; FK references borrowers and loan_products. Status codes expanded.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);

-- Unique constraint on account_number for dedup
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_account_number_unique UNIQUE (account_number);
