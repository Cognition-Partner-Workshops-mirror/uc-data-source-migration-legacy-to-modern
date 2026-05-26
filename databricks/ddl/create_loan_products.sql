-- =============================================================================
-- Delta Lake Table: loan_products (Reference/Dimension)
-- =============================================================================
-- Source: CDW_LN_PROD (legacy all-VARCHAR loan product table)
-- Mapped via: data/mappings/column_mappings.md
--
-- Key transformations from legacy:
--   - PROD_TERM_MOS (string) → term_months (INT)
--   - PROD_MIN_AMT / PROD_MAX_AMT (comma strings) → DECIMAL
--   - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
--   - PROD_EFF_DT / PROD_EXP_DT (MM/DD/YYYY) → DATE
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key for Delta Lake
    product_id          BIGINT          COMMENT 'Surrogate primary key',

    -- Natural key from legacy CDW_LN_PROD.PROD_CD
    code                STRING NOT NULL  COMMENT 'Product code (e.g., FXD30, ARM51)',

    -- Product attributes
    name                STRING NOT NULL  COMMENT 'Product description (from PROD_DESC_TXT)',
    type                STRING NOT NULL  COMMENT 'Product type code: FXD, ARM, FHA, VA (from PROD_TYP_CD)',
    term_months         INT    NOT NULL  COMMENT 'Loan term in months (parsed from PROD_TERM_MOS string)',
    rate_type           STRING NOT NULL  COMMENT 'Rate type: FIXED or VARIABLE (from PROD_RT_TYP)',
    min_amount          DECIMAL(12, 2)  COMMENT 'Minimum loan amount (parsed from PROD_MIN_AMT, commas removed)',
    max_amount          DECIMAL(12, 2)  COMMENT 'Maximum loan amount (parsed from PROD_MAX_AMT, commas removed)',

    -- Status and effective dates
    is_active           BOOLEAN         COMMENT 'Active flag (from PROD_STAT_CD: ACT→true, INA→false)',
    effective_date      DATE            COMMENT 'Product effective date (parsed from PROD_EFF_DT)',
    expiration_date     DATE            COMMENT 'Product expiration date (parsed from PROD_EXP_DT)',

    -- ETL metadata
    _ingestion_ts       TIMESTAMP       COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING          COMMENT 'Source system identifier (CDW_LN_PROD)'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Contains mortgage product definitions with properly typed term, amount, and date fields.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
