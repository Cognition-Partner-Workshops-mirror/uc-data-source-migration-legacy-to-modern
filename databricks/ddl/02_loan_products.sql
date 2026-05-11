-- =============================================================================
-- Delta Lake Table: loan_products
-- Source: CDW_LN_PROD (Legacy Loan Products)
-- =============================================================================
-- Reference / dimension table for loan product types.
-- Status codes are converted to boolean: ACT → true, INA → false.
-- Amount strings with commas are parsed to DECIMAL.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    -- Surrogate key
    id                BIGINT       GENERATED ALWAYS AS IDENTITY,

    -- Product identification
    code              STRING       NOT NULL  COMMENT 'Legacy PROD_CD — natural key',
    name              STRING       NOT NULL  COMMENT 'Mapped from PROD_DESC_TXT',
    type              STRING       NOT NULL  COMMENT 'Mapped from PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months       INT                    COMMENT 'Parsed from PROD_TERM_MOS string → integer',
    rate_type         STRING                 COMMENT 'Mapped from PROD_RT_TYP (FIXED, VARIABLE)',

    -- Amount boundaries
    min_amount        DECIMAL(12,2)          COMMENT 'Parsed from PROD_MIN_AMT (commas removed)',
    max_amount        DECIMAL(12,2)          COMMENT 'Parsed from PROD_MAX_AMT (commas removed)',

    -- Status & validity period
    is_active         BOOLEAN      NOT NULL  COMMENT 'Derived from PROD_STAT_CD: ACT→true, INA→false',
    effective_date    DATE                   COMMENT 'Parsed from PROD_EFF_DT (MM/DD/YYYY)',
    expiration_date   DATE                   COMMENT 'Parsed from PROD_EXP_DT (MM/DD/YYYY)',

    -- Delta Lake metadata
    _ingestion_ts     TIMESTAMP    DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system    STRING       DEFAULT 'CDW_LN_PROD'       COMMENT 'Source system identifier'
)
USING DELTA
COMMENT 'Loan product reference table — migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on product code
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT loan_products_code_unique UNIQUE (code);
