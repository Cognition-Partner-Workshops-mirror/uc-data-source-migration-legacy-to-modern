-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_PROD → loan_products
-- Key transformations:
--   - PROD_TERM_MOS (VARCHAR) → term_months (INT)
--   - PROD_MIN_AMT/MAX_AMT (VARCHAR with commas) → min_amount/max_amount (DECIMAL)
--   - PROD_STAT_CD → is_active (BOOLEAN: ACT→true, INA→false)
--   - PROD_EFF_DT/EXP_DT (VARCHAR MM/DD/YYYY) → effective_date/expiration_date (DATE)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id        BIGINT        GENERATED ALWAYS AS IDENTITY,
    code              STRING        NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30, ARM51)',
    name              STRING        NOT NULL COMMENT 'Legacy PROD_DESC_TXT',
    type              STRING        NOT NULL COMMENT 'Legacy PROD_TYP_CD — FXD, ARM, FHA, VA',
    term_months       INT           NOT NULL COMMENT 'Legacy PROD_TERM_MOS — parsed from VARCHAR',
    rate_type         STRING        NOT NULL COMMENT 'Legacy PROD_RT_TYP — FIXED or VARIABLE',
    min_amount        DECIMAL(12,2) COMMENT 'Legacy PROD_MIN_AMT — parsed from comma-separated string',
    max_amount        DECIMAL(12,2) COMMENT 'Legacy PROD_MAX_AMT — parsed from comma-separated string',
    is_active         BOOLEAN       NOT NULL DEFAULT true COMMENT 'Legacy PROD_STAT_CD: ACT→true, INA→false',
    effective_date    DATE          COMMENT 'Legacy PROD_EFF_DT — parsed from MM/DD/YYYY string',
    expiration_date   DATE          COMMENT 'Legacy PROD_EXP_DT — parsed from MM/DD/YYYY string'
)
USING DELTA
COMMENT 'Modern loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);
