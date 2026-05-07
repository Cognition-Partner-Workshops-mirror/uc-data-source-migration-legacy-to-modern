-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id        BIGINT        GENERATED ALWAYS AS IDENTITY,
    code              STRING        NOT NULL,
    name              STRING        NOT NULL,
    type              STRING,
    term_months       INT,
    rate_type         STRING,
    min_amount        DECIMAL(12, 2),
    max_amount        DECIMAL(12, 2),
    is_active         BOOLEAN       NOT NULL DEFAULT true,
    effective_date    DATE,
    expiration_date   DATE,
    _legacy_prod_cd   STRING        COMMENT 'Original CDW_LN_PROD.PROD_CD for lineage',
    _ingested_at      TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',

    CONSTRAINT loan_products_pk PRIMARY KEY (product_id),
    CONSTRAINT loan_products_code_uq UNIQUE (code)
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.pipeline.source'          = 'CDW_LN_PROD'
);
