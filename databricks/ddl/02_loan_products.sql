-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference / dimension table for loan product definitions.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    code                STRING        NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30, ARM51)',
    name                STRING        NOT NULL COMMENT 'Product description text',
    type                STRING        NOT NULL COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT           COMMENT 'Loan term in months, parsed from string',
    rate_type           STRING        COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12,2) COMMENT 'Minimum loan amount',
    max_amount          DECIMAL(12,2) COMMENT 'Maximum loan amount',
    is_active           BOOLEAN       COMMENT 'Derived: ACT->true, INA->false',
    effective_date      DATE          COMMENT 'Parsed from MM/DD/YYYY string',
    expiration_date     DATE          COMMENT 'Parsed from MM/DD/YYYY string',
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT pk_loan_products PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Modern loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
