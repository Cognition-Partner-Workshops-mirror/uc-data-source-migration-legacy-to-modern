-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Core Data Warehouse)
-- =============================================================================
-- Reference/dimension table for loan product types.
-- Small, slowly-changing table; no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL    COMMENT 'Legacy PROD_CD (FXD30, ARM51, etc.)',
    name                STRING          NOT NULL    COMMENT 'Human-readable product description',
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months, parsed from string',
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2)              COMMENT 'Minimum loan amount',
    max_amount          DECIMAL(12, 2)              COMMENT 'Maximum loan amount',
    is_active           BOOLEAN         NOT NULL    COMMENT 'Derived from PROD_STAT_CD: ACT->true, INA->false',
    effective_date      DATE                        COMMENT 'Product effective date, parsed from MM/DD/YYYY',
    expiration_date     DATE                        COMMENT 'Product expiration date, parsed from MM/DD/YYYY',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
