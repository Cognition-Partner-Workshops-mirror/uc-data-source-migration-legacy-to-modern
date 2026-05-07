-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (legacy Corporate Data Warehouse)
-- =============================================================================
-- Product reference table. Small dimension — no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_code        STRING          NOT NULL    COMMENT 'Legacy PROD_CD — unique product identifier',
    name                STRING          NOT NULL    COMMENT 'Product description (from PROD_DESC_TXT)',
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA (from PROD_TYP_CD)',
    term_months         INT             NOT NULL    COMMENT 'Parsed from PROD_TERM_MOS VARCHAR to integer',
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE (from PROD_RT_TYP)',
    min_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MIN_AMT — commas removed',
    max_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MAX_AMT — commas removed',
    is_active           BOOLEAN         NOT NULL    COMMENT 'Derived from PROD_STAT_CD: ACT→true, INA→false',
    effective_date      DATE                        COMMENT 'Parsed from PROD_EFF_DT MM/DD/YYYY string',
    expiration_date     DATE                        COMMENT 'Parsed from PROD_EXP_DT MM/DD/YYYY string',
    _ingestion_ts       TIMESTAMP       NOT NULL    COMMENT 'Pipeline ingestion timestamp',
    _source_file        STRING                      COMMENT 'Source file path for lineage tracking'
)
USING DELTA
COMMENT 'Loan product reference table — migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
