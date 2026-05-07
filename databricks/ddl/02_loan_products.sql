-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product catalog. Small table, no
-- partitioning needed. Status converted from code to boolean is_active.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key for modern FK relationships
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    -- Legacy product code preserved for traceability and as a natural key
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD from CDW_LN_PROD',
    name                STRING          NOT NULL COMMENT 'Product description (was PROD_DESC_TXT)',
    type                STRING          NOT NULL COMMENT 'Product type code: FXD, ARM, FHA, VA (was PROD_TYP_CD)',
    term_months         INT             COMMENT 'Loan term in months parsed from string (was PROD_TERM_MOS)',
    rate_type           STRING          COMMENT 'FIXED or VARIABLE (was PROD_RT_TYP)',
    min_amount          DECIMAL(12,2)   COMMENT 'Minimum loan amount (was PROD_MIN_AMT)',
    max_amount          DECIMAL(12,2)   COMMENT 'Maximum loan amount (was PROD_MAX_AMT)',
    is_active           BOOLEAN         NOT NULL COMMENT 'Derived from PROD_STAT_CD: ACT->true, INA->false',
    effective_date      DATE            COMMENT 'Product effective date (was PROD_EFF_DT)',
    expiration_date     DATE            COMMENT 'Product expiration date (was PROD_EXP_DT)',
    -- Pipeline metadata
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_PROD' COMMENT 'Source system identifier'
)
USING DELTA
-- No partitioning: small reference table (< 100 rows expected)
COMMENT 'Loan product catalog migrated from CDW_LN_PROD. Small dimension table, no partitioning.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
