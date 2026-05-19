-- =============================================================================
-- Delta Lake Table: loan_products
-- =============================================================================
-- Source: CDW_LN_PROD (legacy loan products table)
--
-- Migration notes:
--   - Replaces all-VARCHAR columns with proper Spark SQL types
--   - Maps cryptic names to readable ones
--     (e.g., PROD_DESC_TXT -> name, PROD_TERM_MOS -> term_months)
--   - PROD_STAT_CD converted to BOOLEAN is_active (ACT -> true, INA -> false)
--   - Amount fields parsed from comma-formatted strings to DECIMAL
--   - Term months parsed from string to INT
--   - Dates parsed from MM/DD/YYYY strings to DATE
--   - Small reference table; no partitioning needed
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.loan_products (
    -- Surrogate primary key
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy PROD_CD preserved as natural key
    code                STRING        NOT NULL,

    -- Product description (from PROD_DESC_TXT)
    name                STRING        NOT NULL,

    -- Product type code (FXD, ARM, FHA, VA — kept as-is)
    type                STRING        NOT NULL,

    -- Term in months: parsed from string to INT (from PROD_TERM_MOS)
    term_months         INT           NOT NULL,

    -- Rate type (FIXED, VARIABLE — direct copy from PROD_RT_TYP)
    rate_type           STRING        NOT NULL,

    -- Amount bounds: parsed from comma-formatted strings to DECIMAL
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),

    -- Active flag: converted from PROD_STAT_CD (ACT -> true, INA -> false)
    is_active           BOOLEAN       DEFAULT true,

    -- Effective/expiration dates: parsed from MM/DD/YYYY strings to DATE
    effective_date      DATE,
    expiration_date     DATE,

    -- Primary key constraint (informational)
    CONSTRAINT pk_loan_products PRIMARY KEY (id)
)
USING DELTA
-- No partitioning — small reference/dimension table
COMMENT 'Loan product catalog migrated from legacy CDW_LN_PROD. Contains product types, terms, rate info, and amount bounds.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);
