-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Not partitioned due to small cardinality (< 100 rows expected).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL,
    name                STRING          NOT NULL,
    type                STRING          NOT NULL,
    term_months         INT             NOT NULL,
    rate_type           STRING          NOT NULL,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN         DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_LN_PROD'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_products
ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
