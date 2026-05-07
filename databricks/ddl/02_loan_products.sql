-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/lookup table for loan product types.
-- Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    code                STRING NOT NULL,
    name                STRING NOT NULL,
    type                STRING,
    term_months         INT,
    rate_type           STRING,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN NOT NULL,
    effective_date      DATE,
    expiration_date     DATE,
    _ingestion_ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    _source_system      STRING DEFAULT 'CDW_LN_PROD'
)
USING DELTA
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD.';

-- Constraints
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_pk PRIMARY KEY (id);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_term_positive
    CHECK (term_months IS NULL OR term_months > 0);

ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_amount_range
    CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount);
