-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Small table; no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL,
    name                STRING          NOT NULL,
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL,
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN         NOT NULL DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _legacy_prod_cd     STRING          COMMENT 'Original CDW_LN_PROD.PROD_CD for lineage',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp'
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
