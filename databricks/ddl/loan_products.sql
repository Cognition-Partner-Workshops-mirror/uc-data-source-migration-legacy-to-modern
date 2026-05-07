-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product types.
-- Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL    COMMENT 'Product code (was PROD_CD)',
    name                STRING          NOT NULL    COMMENT 'Product description (was PROD_DESC_TXT)',
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA (was PROD_TYP_CD)',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months, parsed from VARCHAR (was PROD_TERM_MOS)',
    rate_type           STRING          NOT NULL    COMMENT 'Rate type: FIXED or VARIABLE (was PROD_RT_TYP)',
    min_amount          DECIMAL(12, 2)              COMMENT 'Minimum loan amount, parsed from comma string (was PROD_MIN_AMT)',
    max_amount          DECIMAL(12, 2)              COMMENT 'Maximum loan amount, parsed from comma string (was PROD_MAX_AMT)',
    is_active           BOOLEAN         NOT NULL    COMMENT 'Active flag: ACT->true, INA->false (was PROD_STAT_CD)',
    effective_date      DATE                        COMMENT 'Product effective date, parsed from MM/DD/YYYY (was PROD_EFF_DT)',
    expiration_date     DATE                        COMMENT 'Product expiration date, parsed from MM/DD/YYYY (was PROD_EXP_DT)',
    _migration_source   STRING          DEFAULT 'CDW_LN_PROD' COMMENT 'Source table for lineage tracking',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration run'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Contains product types, terms, and amount ranges.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on product code
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
