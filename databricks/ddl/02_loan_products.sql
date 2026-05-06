-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Product catalog with proper types. Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    code                STRING NOT NULL COMMENT 'Legacy PROD_CD (e.g., FXD30, ARM51)',
    name                STRING NOT NULL COMMENT 'Product description from PROD_DESC_TXT',
    type                STRING NOT NULL COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT NOT NULL COMMENT 'Parsed from VARCHAR string',
    rate_type           STRING NOT NULL COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2) COMMENT 'Parsed from comma-formatted string',
    max_amount          DECIMAL(12, 2) COMMENT 'Parsed from comma-formatted string',
    is_active           BOOLEAN NOT NULL COMMENT 'Derived: ACT->true, INA->false',
    effective_date      DATE COMMENT 'Parsed from MM/DD/YYYY string',
    expiration_date     DATE COMMENT 'Parsed from MM/DD/YYYY string',
    _migration_source   STRING DEFAULT 'CDW_LN_PROD' COMMENT 'Lineage tracking',
    _migrated_at        TIMESTAMP DEFAULT current_timestamp() COMMENT 'Migration timestamp'
)
USING DELTA
COMMENT 'Loan product catalog migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'quality.constraints.code_not_null' = 'code IS NOT NULL',
    'quality.constraints.term_positive' = 'term_months > 0'
);
