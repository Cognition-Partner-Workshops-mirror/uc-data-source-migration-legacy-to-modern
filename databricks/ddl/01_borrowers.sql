-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (legacy Corporate Data Warehouse)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status for efficient filtering on active/inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID — unique borrower identifier',
    first_name          STRING          NOT NULL    COMMENT 'Borrower first name (from BORR_FST_NM)',
    last_name           STRING          NOT NULL    COMMENT 'Borrower last name (from BORR_LST_NM)',
    middle_initial      STRING                      COMMENT 'Middle initial, nullable (from BORR_MID_INIT)',
    ssn_hash            STRING                      COMMENT 'Encrypted SSN token (from BORR_SSN_ENCR)',
    date_of_birth       DATE                        COMMENT 'Parsed from BORR_DOB_DT MM/DD/YYYY string',
    address_line1       STRING                      COMMENT 'Primary address (from BORR_ADDR_LN1)',
    address_line2       STRING                      COMMENT 'Secondary address, nullable (from BORR_ADDR_LN2)',
    city                STRING                      COMMENT 'City (from BORR_CTY_NM)',
    state               STRING                      COMMENT '2-letter state code (from BORR_ST_CD)',
    zip_code            STRING                      COMMENT 'ZIP code (from BORR_ZIP_CD)',
    phone               STRING                      COMMENT 'Phone number (from BORR_PH_NBR)',
    email               STRING                      COMMENT 'Email address (from BORR_EMAIL_ADDR)',
    credit_score        INT                         COMMENT 'Parsed from BORR_CRDT_SCR VARCHAR to integer',
    employment_status   STRING                      COMMENT 'Employment status (from BORR_EMP_STAT)',
    annual_income       DECIMAL(12, 2)              COMMENT 'Parsed from BORR_ANN_INCM — commas removed',
    status              STRING          NOT NULL    COMMENT 'Expanded from BORR_STAT_CD: ACT→ACTIVE, INA→INACTIVE',
    created_at          TIMESTAMP                   COMMENT 'Parsed from BORR_CRET_DT MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from BORR_UPDT_DT MM/DD/YYYY string',
    _ingestion_ts       TIMESTAMP       NOT NULL    COMMENT 'Pipeline ingestion timestamp',
    _source_file        STRING                      COMMENT 'Source file path for lineage tracking'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower dimension table — migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
