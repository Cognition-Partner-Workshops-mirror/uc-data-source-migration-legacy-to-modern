-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_BORR_MSTR → borrowers
-- Key transformations:
--   - BORR_DOB_DT (VARCHAR MM/DD/YYYY) → date_of_birth (DATE)
--   - BORR_CRDT_SCR (VARCHAR) → credit_score (INT)
--   - BORR_ANN_INCM (VARCHAR with commas) → annual_income (DECIMAL)
--   - BORR_STAT_CD (ACT/INA) → status (expanded string)
--   - BORR_REC_TYP dropped (not needed in modern schema)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',
    first_name          STRING          NOT NULL    COMMENT 'Borrower first name (from BORR_FST_NM)',
    last_name           STRING          NOT NULL    COMMENT 'Borrower last name (from BORR_LST_NM)',
    middle_initial      STRING                      COMMENT 'Middle initial (from BORR_MID_INIT), nullable',
    ssn_hash            STRING          NOT NULL    COMMENT 'Encrypted SSN (from BORR_SSN_ENCR), re-encrypt recommended',
    date_of_birth       DATE                        COMMENT 'Parsed from BORR_DOB_DT (MM/DD/YYYY → DATE)',
    address_line1       STRING                      COMMENT 'Primary address (from BORR_ADDR_LN1)',
    address_line2       STRING                      COMMENT 'Secondary address (from BORR_ADDR_LN2), often NULL',
    city                STRING                      COMMENT 'City (from BORR_CTY_NM)',
    state               STRING                      COMMENT '2-letter state code (from BORR_ST_CD)',
    zip_code            STRING                      COMMENT 'ZIP code (from BORR_ZIP_CD)',
    phone               STRING                      COMMENT 'Phone number (from BORR_PH_NBR)',
    email               STRING                      COMMENT 'Email address (from BORR_EMAIL_ADDR)',
    credit_score        INT                         COMMENT 'Parsed from BORR_CRDT_SCR (VARCHAR → INT)',
    employment_status   STRING                      COMMENT 'Employment status (from BORR_EMP_STAT)',
    annual_income       DECIMAL(12, 2)              COMMENT 'Parsed from BORR_ANN_INCM (remove commas → DECIMAL)',
    status              STRING          NOT NULL    COMMENT 'Expanded from BORR_STAT_CD: ACT→ACTIVE, INA→INACTIVE',
    created_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from BORR_CRET_DT (MM/DD/YYYY → TIMESTAMP)',
    updated_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from BORR_UPDT_DT (MM/DD/YYYY → TIMESTAMP)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR'     COMMENT 'Source table identifier'
)
USING DELTA
-- Partitioning by status supports common query patterns (active borrowers lookup)
PARTITIONED BY (status)
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR. All VARCHAR fields converted to proper types.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
