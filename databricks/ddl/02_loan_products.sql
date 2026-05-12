-- =============================================================================
-- Delta Lake Table: loan_products (dimension table)
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Migrated from the legacy CDW_LN_PROD table. The PROD_STAT_CD code is
-- converted to a boolean is_active flag (ACT→true, INA→false). Term months
-- and amount ranges are parsed from VARCHAR to proper numeric types.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy PROD_CD preserved as natural key (legacy: PROD_CD)
    code                STRING          NOT NULL
        COMMENT 'Legacy product code from CDW_LN_PROD',

    -- Product description (legacy: PROD_DESC_TXT)
    name                STRING          NOT NULL
        COMMENT 'Human-readable product name',

    -- Product type code: FXD, ARM, FHA, VA (legacy: PROD_TYP_CD)
    type                STRING          NOT NULL
        COMMENT 'Product type code: FXD, ARM, FHA, VA',

    -- Parsed from VARCHAR (legacy: PROD_TERM_MOS)
    term_months         INT             NOT NULL
        COMMENT 'Loan term in months, parsed from legacy VARCHAR',

    -- Rate type: FIXED or VARIABLE (legacy: PROD_RT_TYP)
    rate_type           STRING          NOT NULL
        COMMENT 'Interest rate type: FIXED or VARIABLE',

    -- Parsed from comma-formatted strings (legacy: PROD_MIN_AMT, PROD_MAX_AMT)
    min_amount          DECIMAL(12, 2)
        COMMENT 'Minimum loan amount, parsed from legacy comma-formatted string',
    max_amount          DECIMAL(12, 2)
        COMMENT 'Maximum loan amount, parsed from legacy comma-formatted string',

    -- Converted from status code to boolean (ACT→true, INA→false) (legacy: PROD_STAT_CD)
    is_active           BOOLEAN         DEFAULT true
        COMMENT 'Whether the product is active; converted from legacy PROD_STAT_CD',

    -- Parsed from MM/DD/YYYY strings (legacy: PROD_EFF_DT, PROD_EXP_DT)
    effective_date      DATE
        COMMENT 'Product effective date, parsed from legacy MM/DD/YYYY string',
    expiration_date     DATE
        COMMENT 'Product expiration date, parsed from legacy MM/DD/YYYY string',

    -- Audit column
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
        COMMENT 'Timestamp when the row was loaded by the migration pipeline'
)
USING DELTA
COMMENT 'Modern loan product dimension table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on product code for FK lookups during loan_accounts ingestion
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
