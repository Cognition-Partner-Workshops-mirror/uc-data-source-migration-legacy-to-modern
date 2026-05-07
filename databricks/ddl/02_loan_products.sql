-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Reference/dimension table for loan product offerings.
-- Small table (~tens of rows), no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    code                STRING NOT NULL,
    name                STRING NOT NULL,
    type                STRING NOT NULL,
    term_months         INT NOT NULL,
    rate_type           STRING NOT NULL,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,

    CONSTRAINT loan_products_pk PRIMARY KEY (id),
    CONSTRAINT loan_products_code_uq UNIQUE (code),
    CONSTRAINT loan_products_type_values CHECK (type IN ('FXD', 'ARM', 'FHA', 'VA')),
    CONSTRAINT loan_products_rate_type_values CHECK (rate_type IN ('FIXED', 'VARIABLE')),
    CONSTRAINT loan_products_term_pos CHECK (term_months > 0),
    CONSTRAINT loan_products_amount_range CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount)
)
USING DELTA
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Contains product definitions with proper types.';
