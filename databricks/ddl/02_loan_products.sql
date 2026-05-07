-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy CDW)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_key         BIGINT GENERATED ALWAYS AS IDENTITY,
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
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. No partitioning due to small cardinality.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);

-- Constraints
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_type_valid
    CHECK (type IN ('FXD', 'ARM', 'FHA', 'VA'));

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_rate_type_valid
    CHECK (rate_type IN ('FIXED', 'VARIABLE'));

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_amount_range
    CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount);
