-- =============================================================================
-- Delta Lake: loan_products table
-- Source: CDW_LN_PROD (legacy)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD (FXD30, ARM51, etc.)',
    name                STRING          NOT NULL COMMENT 'Product description',
    type                STRING          NOT NULL COMMENT 'FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL COMMENT 'Parsed from VARCHAR',
    rate_type           STRING          NOT NULL COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12,2)   NOT NULL COMMENT 'Parsed from comma-formatted string',
    max_amount          DECIMAL(12,2)   NOT NULL COMMENT 'Parsed from comma-formatted string',
    is_active           BOOLEAN         NOT NULL COMMENT 'ACT->true, INA->false',
    effective_date      DATE            COMMENT 'Parsed from MM/DD/YYYY',
    expiration_date     DATE            COMMENT 'Parsed from MM/DD/YYYY',

    CONSTRAINT loan_products_pk PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Loan product catalog migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

CREATE INDEX IF NOT EXISTS idx_loan_products_code
ON loan_warehouse.loan_products (code);
