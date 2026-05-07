-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (legacy)
-- =============================================================================
-- Reference/dimension table for loan product catalog. Small table, no
-- partitioning needed. Uses proper types for term, amounts, and dates.
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
    _migration_source   STRING          DEFAULT 'CDW_LN_PROD',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
