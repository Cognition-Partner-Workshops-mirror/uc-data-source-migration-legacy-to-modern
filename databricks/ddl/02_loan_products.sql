-- =============================================================================
-- Delta Lake Table: loan_products
-- =============================================================================
-- Migrated from legacy CDW_LN_PROD table.
-- Reference/dimension table for loan product types.
-- Term months parsed from VARCHAR to INT.
-- Min/max amounts parsed from comma-formatted strings to DECIMAL.
-- Status code mapped to BOOLEAN is_active flag (ACT -> true, INA -> false).
-- Date strings (MM/DD/YYYY) converted to DATE type.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key generated during ingestion
    product_id          BIGINT          COMMENT 'Auto-generated surrogate primary key',
    -- Natural key carried from legacy CDW_LN_PROD.PROD_CD
    code                STRING NOT NULL  COMMENT 'Product code from CDW_LN_PROD.PROD_CD (e.g. FXD30, ARM51)',
    name                STRING NOT NULL  COMMENT 'Product description, mapped from PROD_DESC_TXT',
    type                STRING NOT NULL  COMMENT 'Product type code, mapped from PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months         INT    NOT NULL  COMMENT 'Parsed from PROD_TERM_MOS (VARCHAR -> INT)',
    rate_type           STRING NOT NULL  COMMENT 'Rate type, mapped from PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount          DECIMAL(12, 2)  COMMENT 'Parsed from PROD_MIN_AMT (comma-formatted string -> DECIMAL)',
    max_amount          DECIMAL(12, 2)  COMMENT 'Parsed from PROD_MAX_AMT (comma-formatted string -> DECIMAL)',
    is_active           BOOLEAN         COMMENT 'Derived from PROD_STAT_CD: ACT -> true, INA -> false',
    effective_date      DATE            COMMENT 'Parsed from PROD_EFF_DT (MM/DD/YYYY -> DATE)',
    expiration_date     DATE            COMMENT 'Parsed from PROD_EXP_DT (MM/DD/YYYY -> DATE)',
    -- Ingestion metadata
    _ingestion_ts       TIMESTAMP       COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING          COMMENT 'Source system identifier (CDW_LN_PROD)'
)
USING DELTA
-- Small reference table; no partitioning needed
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Contains product definitions, terms, and rate types.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
