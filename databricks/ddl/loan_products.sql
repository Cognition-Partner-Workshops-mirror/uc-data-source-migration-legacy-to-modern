-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Small table, no partitioning needed.
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
    is_active           BOOLEAN         NOT NULL DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _migration_source   STRING          DEFAULT 'CDW_LN_PROD',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Small dimension table, no partitioning required.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
