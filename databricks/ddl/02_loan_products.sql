-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
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
    _migration_source   STRING        DEFAULT 'CDW_LN_PROD',
    _migrated_at        TIMESTAMP     DEFAULT current_timestamp()
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

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_type_values
    CHECK (type IN ('FXD', 'ARM', 'FHA', 'VA'));

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_rate_type_values
    CHECK (rate_type IN ('FIXED', 'VARIABLE'));

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_amount_range
    CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount);
