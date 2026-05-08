-- =============================================================================
-- Delta Lake Table: loan_products
-- =============================================================================
-- Source: CDW_LN_PROD (legacy loan products table)
-- Migration: Term months and amounts converted from VARCHAR to proper numeric
--            types; PROD_STAT_CD converted to a BOOLEAN is_active flag.
-- Partitioning: None — small reference/dimension table (low cardinality).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL    COMMENT 'Mapped from PROD_CD; legacy product code (FXD30, ARM51, etc.)',
    name                STRING          NOT NULL    COMMENT 'Mapped from PROD_DESC_TXT',
    type                STRING          NOT NULL    COMMENT 'Mapped from PROD_TYP_CD (FXD, ARM, FHA, VA)',
    term_months         INT             NOT NULL    COMMENT 'Parsed from PROD_TERM_MOS (string to integer)',
    rate_type           STRING          NOT NULL    COMMENT 'Mapped from PROD_RT_TYP (FIXED, VARIABLE)',
    min_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MIN_AMT (comma-formatted string)',
    max_amount          DECIMAL(12, 2)              COMMENT 'Parsed from PROD_MAX_AMT (comma-formatted string)',
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE
                                                    COMMENT 'Derived from PROD_STAT_CD: ACT→true, INA→false',
    effective_date      DATE                        COMMENT 'Parsed from PROD_EFF_DT (MM/DD/YYYY string)',
    expiration_date     DATE                        COMMENT 'Parsed from PROD_EXP_DT (MM/DD/YYYY string)',

    CONSTRAINT pk_loan_products PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Loan product reference table migrated from legacy CDW_LN_PROD'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'quality'                          = 'gold'
);

-- Unique constraint on legacy product code for FK lookups during migration
ALTER TABLE loan_warehouse.loan_products
    ADD CONSTRAINT uq_loan_products_code UNIQUE (code);
