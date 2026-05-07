-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference/dimension table for loan product types.
-- Small table, no partitioning needed.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30, ARM51)',
    name                STRING          NOT NULL COMMENT 'Legacy PROD_DESC_TXT',
    type                STRING          NOT NULL COMMENT 'Legacy PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months         INT             NOT NULL COMMENT 'Legacy PROD_TERM_MOS parsed from string',
    rate_type           STRING          NOT NULL COMMENT 'Legacy PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount          DECIMAL(12, 2)  COMMENT 'Legacy PROD_MIN_AMT parsed from comma-string',
    max_amount          DECIMAL(12, 2)  COMMENT 'Legacy PROD_MAX_AMT parsed from comma-string',
    is_active           BOOLEAN         NOT NULL DEFAULT true COMMENT 'Legacy PROD_STAT_CD: ACT->true, INA->false',
    effective_date      DATE            COMMENT 'Legacy PROD_EFF_DT parsed from MM/DD/YYYY',
    expiration_date     DATE            COMMENT 'Legacy PROD_EXP_DT parsed from MM/DD/YYYY',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT loan_products_pk PRIMARY KEY (product_key),
    CONSTRAINT loan_products_code_uq UNIQUE (code)
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD. No partitioning (small dimension table).'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
