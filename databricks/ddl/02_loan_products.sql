-- =============================================================================
-- Delta Lake Table: loan_products
-- =============================================================================
-- Source: CDW_LN_PROD (legacy all-VARCHAR loan product reference table)
-- Target: loan_products (modern typed product dimension)
--
-- Key transformations from legacy:
--   - PROD_TERM_MOS (VARCHAR) → term_months (INT)
--   - PROD_MIN_AMT / PROD_MAX_AMT (VARCHAR with commas) → DECIMAL
--   - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
--   - PROD_EFF_DT / PROD_EXP_DT (VARCHAR MM/DD/YYYY) → DATE
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Natural key carried from legacy CDW_LN_PROD.PROD_CD
    code                STRING          NOT NULL,

    -- Product description — renamed from PROD_DESC_TXT for clarity
    name                STRING          NOT NULL,

    -- Product type code (FXD, ARM, FHA, VA) — direct copy
    type                STRING          NOT NULL,

    -- Term in months — parsed from legacy VARCHAR
    term_months         INT             NOT NULL,

    -- Rate type (FIXED, VARIABLE) — direct copy
    rate_type           STRING          NOT NULL,

    -- Amount range — parsed from legacy comma-formatted VARCHAR to decimal
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),

    -- Active flag — converted from legacy PROD_STAT_CD (ACT→true, INA→false)
    is_active           BOOLEAN         DEFAULT true,

    -- Effective/expiration dates — parsed from legacy MM/DD/YYYY VARCHAR
    effective_date      DATE,
    expiration_date     DATE,

    -- ETL metadata columns for lineage tracking
    _etl_loaded_at      TIMESTAMP       DEFAULT current_timestamp(),
    _etl_source         STRING          DEFAULT 'CDW_LN_PROD'
)
USING DELTA
-- Small dimension table; no partitioning needed (< thousands of rows typically)
COMMENT 'Modern loan product reference table migrated from legacy CDW_LN_PROD. Status abbreviation converted to boolean.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);

-- Unique constraint on product code for dedup
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
