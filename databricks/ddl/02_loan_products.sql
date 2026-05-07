-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_PROD → loan_products
-- Small dimension table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD (e.g., FXD30, ARM51)',
    name                STRING          NOT NULL COMMENT 'Legacy PROD_DESC_TXT',
    type                STRING          NOT NULL COMMENT 'Legacy PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months         INT             NOT NULL COMMENT 'Legacy PROD_TERM_MOS, parsed from VARCHAR',
    rate_type           STRING          NOT NULL COMMENT 'Legacy PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount          DECIMAL(12, 2)  COMMENT 'Legacy PROD_MIN_AMT, parsed from comma-formatted string',
    max_amount          DECIMAL(12, 2)  COMMENT 'Legacy PROD_MAX_AMT, parsed from comma-formatted string',
    is_active           BOOLEAN         NOT NULL COMMENT 'Legacy PROD_STAT_CD: ACT→true, INA→false',
    effective_date      DATE            COMMENT 'Legacy PROD_EFF_DT, parsed from MM/DD/YYYY',
    expiration_date     DATE            COMMENT 'Legacy PROD_EXP_DT, parsed from MM/DD/YYYY',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_PROD' COMMENT 'Source system identifier'
)
USING DELTA
COMMENT 'Loan product catalog migrated from legacy CDW_LN_PROD table'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
