-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (legacy)
-- =============================================================================
-- Product reference table. Small dimension — no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30, ARM51)',
    name                STRING          NOT NULL COMMENT 'Mapped from PROD_DESC_TXT',
    type                STRING          NOT NULL COMMENT 'Mapped from PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months         INT             NOT NULL COMMENT 'Parsed from PROD_TERM_MOS (string to int)',
    rate_type           STRING          NOT NULL COMMENT 'Mapped from PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount          DECIMAL(12, 2)  COMMENT 'Parsed from PROD_MIN_AMT (remove commas)',
    max_amount          DECIMAL(12, 2)  COMMENT 'Parsed from PROD_MAX_AMT (remove commas)',
    is_active           BOOLEAN         NOT NULL DEFAULT true COMMENT 'Derived from PROD_STAT_CD: ACT→true, INA→false',
    effective_date      DATE            COMMENT 'Parsed from PROD_EFF_DT (MM/DD/YYYY)',
    expiration_date     DATE            COMMENT 'Parsed from PROD_EXP_DT (MM/DD/YYYY)',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration load',
    _source_system      STRING          DEFAULT 'CDW_LN_PROD' COMMENT 'Source table identifier',

    CONSTRAINT loan_products_pk PRIMARY KEY (product_key),
    CONSTRAINT loan_products_code_uq UNIQUE (code)
)
USING DELTA
COMMENT 'Loan product reference table — migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
