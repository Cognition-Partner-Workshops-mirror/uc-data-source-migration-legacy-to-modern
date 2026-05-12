-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_BORR_MSTR → borrowers
-- Key transformations:
--   - BORR_DOB_DT (VARCHAR MM/DD/YYYY) → date_of_birth (DATE)
--   - BORR_CRDT_SCR (VARCHAR) → credit_score (INT)
--   - BORR_ANN_INCM (VARCHAR with commas) → annual_income (DECIMAL)
--   - BORR_STAT_CD (abbreviated) → status (expanded: ACT→ACTIVE, INA→INACTIVE)
--   - BORR_REC_TYP dropped (not needed in modern schema)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id       BIGINT        GENERATED ALWAYS AS IDENTITY,
    external_id       STRING        NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name        STRING        NOT NULL COMMENT 'Legacy BORR_FST_NM',
    last_name         STRING        NOT NULL COMMENT 'Legacy BORR_LST_NM',
    middle_initial    STRING        COMMENT 'Legacy BORR_MID_INIT — nullable, single character',
    ssn_hash          STRING        NOT NULL COMMENT 'Legacy BORR_SSN_ENCR — re-encryption recommended',
    date_of_birth     DATE          COMMENT 'Legacy BORR_DOB_DT — parsed from MM/DD/YYYY string',
    address_line1     STRING        COMMENT 'Legacy BORR_ADDR_LN1',
    address_line2     STRING        COMMENT 'Legacy BORR_ADDR_LN2 — nullable',
    city              STRING        COMMENT 'Legacy BORR_CTY_NM',
    state             STRING        COMMENT 'Legacy BORR_ST_CD — 2-letter code',
    zip_code          STRING        COMMENT 'Legacy BORR_ZIP_CD',
    phone             STRING        COMMENT 'Legacy BORR_PH_NBR',
    email             STRING        COMMENT 'Legacy BORR_EMAIL_ADDR',
    credit_score      INT           COMMENT 'Legacy BORR_CRDT_SCR — parsed from VARCHAR to INT, range 300-850',
    employment_status STRING        COMMENT 'Legacy BORR_EMP_STAT — EMPLOYED, SELF-EMP, RETIRED, etc.',
    annual_income     DECIMAL(12,2) COMMENT 'Legacy BORR_ANN_INCM — parsed from comma-separated string',
    status            STRING        NOT NULL DEFAULT 'ACTIVE' COMMENT 'Legacy BORR_STAT_CD expanded: ACT→ACTIVE, INA→INACTIVE',
    created_at        TIMESTAMP     COMMENT 'Legacy BORR_CRET_DT — parsed from MM/DD/YYYY string',
    updated_at        TIMESTAMP     COMMENT 'Legacy BORR_UPDT_DT — parsed from MM/DD/YYYY string'
)
USING DELTA
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);
