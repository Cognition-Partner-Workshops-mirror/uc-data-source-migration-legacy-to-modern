-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product definitions. Small table, so no
-- partitioning is applied. Z-ORDER by type recommended for scan efficiency.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD',
    name                STRING          NOT NULL COMMENT 'Product description',
    type                STRING          NOT NULL COMMENT 'FXD, ARM, FHA, VA',
    term_months         INT,
    rate_type           STRING          COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2),
    max_amount          DECIMAL(12, 2),
    is_active           BOOLEAN         NOT NULL DEFAULT true,
    effective_date      DATE,
    expiration_date     DATE,
    _migration_src      STRING          DEFAULT 'CDW_LN_PROD' COMMENT 'Source table for lineage',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Migration run timestamp',

    CONSTRAINT loan_products_pk PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
