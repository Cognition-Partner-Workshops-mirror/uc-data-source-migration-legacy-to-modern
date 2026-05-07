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
    type                STRING          NOT NULL,
    term_months         INT             NOT NULL,
    rate_type           STRING          NOT NULL,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN         DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _migration_source   STRING          DEFAULT 'CDW_LN_PROD',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. No partitioning due to small cardinality.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_not_null EXPECT (code IS NOT NULL);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_type_valid EXPECT (type IN ('FXD', 'ARM', 'FHA', 'VA'));

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_rate_type_valid EXPECT (rate_type IN ('FIXED', 'VARIABLE'));
