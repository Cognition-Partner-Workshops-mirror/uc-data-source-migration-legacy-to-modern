-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (legacy all-VARCHAR loan product reference table)
-- =============================================================================
-- Reference/dimension table for loan product definitions. The legacy status
-- code PROD_STAT_CD (ACT/INA) is converted to a boolean is_active flag.
-- Amount fields are converted from comma-formatted VARCHARs to DECIMAL.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Natural key from legacy CDW_LN_PROD.PROD_CD
    code                STRING          NOT NULL    COMMENT 'Product code e.g. FXD30, ARM51 (PROD_CD)',
    name                STRING          NOT NULL    COMMENT 'Product description (PROD_DESC_TXT)',
    type                STRING          NOT NULL    COMMENT 'Product type code: FXD, ARM, FHA, VA (PROD_TYP_CD)',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months parsed from string (PROD_TERM_MOS)',
    rate_type           STRING          NOT NULL    COMMENT 'FIXED or VARIABLE (PROD_RT_TYP)',

    -- Amount range (parsed from comma-formatted strings)
    min_amount          DECIMAL(12,2)   NOT NULL    COMMENT 'Minimum loan amount (PROD_MIN_AMT)',
    max_amount          DECIMAL(12,2)   NOT NULL    COMMENT 'Maximum loan amount (PROD_MAX_AMT)',

    -- Status converted from code to boolean
    is_active           BOOLEAN         NOT NULL    COMMENT 'ACT -> true, INA -> false (PROD_STAT_CD)',

    -- Date range (parsed from MM/DD/YYYY strings)
    effective_date      DATE            NOT NULL    COMMENT 'Product effective date (PROD_EFF_DT)',
    expiration_date     DATE            NOT NULL    COMMENT 'Product expiration date (PROD_EXP_DT)',

    -- Ingestion metadata
    _legacy_source      STRING          DEFAULT 'CDW_LN_PROD'    COMMENT 'Source table for lineage',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD. Amounts parsed to DECIMAL, status to BOOLEAN.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
