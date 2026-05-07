-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product types.
-- Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_key         BIGINT GENERATED ALWAYS AS IDENTITY,
    code                STRING        NOT NULL,
    name                STRING        NOT NULL,
    type                STRING        NOT NULL,
    term_months         INT           NOT NULL,
    rate_type           STRING        NOT NULL,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN       DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp(),
    _source_system      STRING        DEFAULT 'CDW_LN_PROD'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.constraints.code'         = 'code IS NOT NULL',
    'quality.constraints.name'         = 'name IS NOT NULL',
    'quality.constraints.type'         = 'type IS NOT NULL'
);
