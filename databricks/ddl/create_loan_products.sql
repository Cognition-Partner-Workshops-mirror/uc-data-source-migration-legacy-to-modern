-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (legacy)
-- =============================================================================
-- Reference / dimension table for loan product types.
-- Small table — no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id        BIGINT        GENERATED ALWAYS AS IDENTITY,
    code              STRING        NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30, ARM51)',
    name              STRING        NOT NULL COMMENT 'Legacy PROD_DESC_TXT',
    type              STRING        NOT NULL COMMENT 'Legacy PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months       INT           NOT NULL COMMENT 'Legacy PROD_TERM_MOS — parsed from VARCHAR',
    rate_type         STRING        NOT NULL COMMENT 'Legacy PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount        DECIMAL(12,2) COMMENT 'Legacy PROD_MIN_AMT — parsed from comma-formatted string',
    max_amount        DECIMAL(12,2) COMMENT 'Legacy PROD_MAX_AMT — parsed from comma-formatted string',
    is_active         BOOLEAN       NOT NULL DEFAULT true COMMENT 'Legacy PROD_STAT_CD: ACT->true, INA->false',
    effective_date    DATE          COMMENT 'Legacy PROD_EFF_DT — parsed from MM/DD/YYYY',
    expiration_date   DATE          COMMENT 'Legacy PROD_EXP_DT — parsed from MM/DD/YYYY',
    _migration_ts     TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system    STRING        DEFAULT 'CDW_LN_PROD' COMMENT 'Source table identifier'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Unique constraint on product code
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
