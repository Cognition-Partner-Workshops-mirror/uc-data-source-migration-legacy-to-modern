-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Reference/dimension table for available loan product types.
-- Small table (no partitioning needed) — typically < 100 rows.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Primary key (auto-generated surrogate key)
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Product code from legacy (CDW_LN_PROD.PROD_CD)
    code                STRING NOT NULL,

    -- Human-readable product name (from PROD_DESC_TXT)
    name                STRING NOT NULL,

    -- Product classification (FXD, ARM, FHA, VA)
    type                STRING NOT NULL,

    -- Loan term in months (parsed from VARCHAR)
    term_months         INT NOT NULL,

    -- Rate type indicator (FIXED, VARIABLE)
    rate_type           STRING NOT NULL,

    -- Allowed loan amount range (parsed from comma-formatted strings)
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),

    -- Active flag (converted from PROD_STAT_CD: ACT→true, INA→false)
    is_active           BOOLEAN DEFAULT true,

    -- Validity period (parsed from MM/DD/YYYY strings)
    effective_date      DATE,
    expiration_date     DATE,

    -- Constraints
    CONSTRAINT pk_loan_products PRIMARY KEY (id),
    CONSTRAINT uq_loan_products_code UNIQUE (code)
)
USING DELTA
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Contains product definitions, terms, rate types, and amount ranges.';
