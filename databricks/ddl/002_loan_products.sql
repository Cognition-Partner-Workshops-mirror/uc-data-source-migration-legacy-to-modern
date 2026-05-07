-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference table for available loan product types. Converts string-encoded
-- term lengths and amount ranges to proper numeric types.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL,
    name                STRING          NOT NULL,
    type                STRING          NOT NULL COMMENT 'FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL,
    rate_type           STRING          NOT NULL COMMENT 'FIXED or VARIABLE',
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
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality'                          = 'gold'
);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
