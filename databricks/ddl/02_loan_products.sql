-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Core Data Warehouse)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Small cardinality table; no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL,
    name                STRING          NOT NULL,
    type                STRING          NOT NULL    COMMENT 'Product type: FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL,
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN         NOT NULL DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _load_ts            TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_LN_PROD',

    CONSTRAINT pk_loan_products PRIMARY KEY (product_id),
    CONSTRAINT uq_loan_products_code UNIQUE (code)
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
