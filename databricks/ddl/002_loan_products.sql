-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy CDW)
-- =============================================================================
-- Reference/dimension table for loan product definitions.
-- Small table; no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_modernized.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL    COMMENT 'Product code (FXD30, FXD15, ARM51, FHA30, VA30)',
    name                STRING          NOT NULL    COMMENT 'Full product description',
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months parsed from VARCHAR',
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2)              COMMENT 'Minimum loan amount parsed from comma-formatted string',
    max_amount          DECIMAL(12, 2)              COMMENT 'Maximum loan amount parsed from comma-formatted string',
    is_active           BOOLEAN         NOT NULL DEFAULT true
                                                    COMMENT 'Derived from PROD_STAT_CD: ACT->true, INA->false',
    effective_date      DATE                        COMMENT 'Product effective date parsed from MM/DD/YYYY',
    expiration_date     DATE                        COMMENT 'Product expiration date parsed from MM/DD/YYYY',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Timestamp when record was migrated'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_modernized.loan_products
    ADD CONSTRAINT loan_products_code_not_null EXPECT (code IS NOT NULL)
    VIOLATION (FAIL UPDATE);
