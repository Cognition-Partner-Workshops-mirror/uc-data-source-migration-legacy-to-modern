-- =============================================================================
-- Delta Lake DDL: loan_products
-- Source: CDW_LN_PROD (Legacy CDW)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    code                STRING          NOT NULL    COMMENT 'Legacy: PROD_CD — unique product code (natural key)',
    name                STRING          NOT NULL    COMMENT 'Legacy: PROD_DESC_TXT — product description',
    type                STRING          NOT NULL    COMMENT 'Legacy: PROD_TYP_CD — product type (FXD, ARM, FHA, VA)',
    term_months         INT             NOT NULL    COMMENT 'Legacy: PROD_TERM_MOS — parsed from VARCHAR to integer',
    rate_type           STRING          NOT NULL    COMMENT 'Legacy: PROD_RT_TYP — FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2)              COMMENT 'Legacy: PROD_MIN_AMT — parsed from comma-formatted string',
    max_amount          DECIMAL(12, 2)              COMMENT 'Legacy: PROD_MAX_AMT — parsed from comma-formatted string',
    is_active           BOOLEAN                     COMMENT 'Legacy: PROD_STAT_CD — ACT mapped to true, INA mapped to false',
    effective_date      DATE                        COMMENT 'Legacy: PROD_EFF_DT — parsed from MM/DD/YYYY string',
    expiration_date     DATE                        COMMENT 'Legacy: PROD_EXP_DT — parsed from MM/DD/YYYY string',
    _migration_source   STRING                      COMMENT 'Source system identifier for lineage tracking',
    _migrated_at        TIMESTAMP                   COMMENT 'Timestamp when record was migrated'
)
USING DELTA
COMMENT 'Loan product reference data migrated from CDW_LN_PROD. Small reference table — no partitioning needed.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
