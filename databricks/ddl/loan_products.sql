-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_LN_PROD → loan_products
-- Key transformations:
--   - PROD_TERM_MOS (VARCHAR) → term_months (INT)
--   - PROD_MIN_AMT / PROD_MAX_AMT (VARCHAR with commas) → DECIMAL
--   - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
--   - PROD_EFF_DT / PROD_EXP_DT (VARCHAR MM/DD/YYYY) → DATE
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL    COMMENT 'Product code (from PROD_CD), e.g. FXD30, ARM51',
    name                STRING          NOT NULL    COMMENT 'Product description (from PROD_DESC_TXT)',
    type                STRING          NOT NULL    COMMENT 'Product type code (from PROD_TYP_CD): FXD, ARM, FHA, VA',
    term_months         INT                         COMMENT 'Parsed from PROD_TERM_MOS (VARCHAR → INT)',
    rate_type           STRING                      COMMENT 'Rate type (from PROD_RT_TYP): FIXED, VARIABLE',
    min_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MIN_AMT (remove commas → DECIMAL)',
    max_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MAX_AMT (remove commas → DECIMAL)',
    is_active           BOOLEAN         NOT NULL    COMMENT 'Derived from PROD_STAT_CD: ACT→true, INA→false',
    effective_date      DATE                        COMMENT 'Parsed from PROD_EFF_DT (MM/DD/YYYY → DATE)',
    expiration_date     DATE                        COMMENT 'Parsed from PROD_EXP_DT (MM/DD/YYYY → DATE)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_LN_PROD'       COMMENT 'Source table identifier'
)
USING DELTA
-- Small reference table; no partitioning needed
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Status codes converted to boolean.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
