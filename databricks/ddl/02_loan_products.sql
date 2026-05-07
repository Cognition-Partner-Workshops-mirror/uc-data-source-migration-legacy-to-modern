-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.loan_products (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    code                STRING NOT NULL,
    name                STRING NOT NULL,
    type                STRING NOT NULL,
    term_months         INT,
    rate_type           STRING,
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN NOT NULL DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,

    CONSTRAINT pk_loan_products PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);
