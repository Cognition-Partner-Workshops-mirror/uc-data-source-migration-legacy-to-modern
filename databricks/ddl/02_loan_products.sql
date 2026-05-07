-- =============================================================================
-- Delta Lake Table: loan_products (reference/dimension table)
-- Source: CDW_LN_PROD
-- =============================================================================
-- Loan product reference table. Small dimension table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id        BIGINT GENERATED ALWAYS AS IDENTITY,
    code              STRING NOT NULL,
    name              STRING NOT NULL,
    type              STRING,
    term_months       INT,
    rate_type         STRING,
    min_amount        DECIMAL(12, 2),
    max_amount        DECIMAL(12, 2),
    is_active         BOOLEAN NOT NULL,
    effective_date    DATE,
    expiration_date   DATE,
    _ingestion_ts     TIMESTAMP DEFAULT current_timestamp(),
    _source_system    STRING DEFAULT 'CDW_LEGACY'
)
USING DELTA
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Small dimension, no partitioning required.';

-- Constraints
ALTER TABLE loan_warehouse.loan_products
ADD CONSTRAINT loan_products_code_unique UNIQUE (code);

ALTER TABLE loan_warehouse.loan_products
ADD CONSTRAINT loan_products_rate_type_check CHECK (rate_type IN ('FIXED', 'VARIABLE'));
