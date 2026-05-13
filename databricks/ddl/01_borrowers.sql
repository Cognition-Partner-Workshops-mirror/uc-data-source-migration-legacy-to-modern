-- =============================================================================
-- Delta Lake Table: borrowers
-- =============================================================================
-- Migrated from legacy CDW_BORR_MSTR table.
-- Borrower dimension table extracted from the denormalized legacy schema.
-- All VARCHAR columns have been converted to proper Spark SQL types.
-- Status codes expanded from abbreviations (ACT -> Active, INA -> Inactive).
-- Date strings (MM/DD/YYYY) converted to DATE / TIMESTAMP types.
-- Amount strings with commas converted to DECIMAL types.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    -- Surrogate key generated during ingestion
    borrower_id         BIGINT          COMMENT 'Auto-generated surrogate primary key',
    -- Natural key carried from legacy CDW_BORR_MSTR.BORR_ID
    external_id         STRING NOT NULL  COMMENT 'Legacy borrower identifier from CDW_BORR_MSTR.BORR_ID',
    first_name          STRING NOT NULL  COMMENT 'Borrower first name, mapped from BORR_FST_NM',
    last_name           STRING NOT NULL  COMMENT 'Borrower last name, mapped from BORR_LST_NM',
    middle_initial      STRING          COMMENT 'Middle initial, mapped from BORR_MID_INIT',
    ssn_hash            STRING          COMMENT 'Encrypted SSN carried from BORR_SSN_ENCR (re-encrypt recommended)',
    date_of_birth       DATE            COMMENT 'Parsed from BORR_DOB_DT (MM/DD/YYYY string)',
    address_line1       STRING          COMMENT 'Primary address line, mapped from BORR_ADDR_LN1',
    address_line2       STRING          COMMENT 'Secondary address line, mapped from BORR_ADDR_LN2',
    city                STRING          COMMENT 'City name, mapped from BORR_CTY_NM',
    state               STRING          COMMENT 'Two-letter state code, mapped from BORR_ST_CD',
    zip_code            STRING          COMMENT 'ZIP code, mapped from BORR_ZIP_CD',
    phone               STRING          COMMENT 'Phone number, mapped from BORR_PH_NBR',
    email               STRING          COMMENT 'Email address, mapped from BORR_EMAIL_ADDR',
    credit_score        INT             COMMENT 'Parsed from BORR_CRDT_SCR (VARCHAR -> INT)',
    employment_status   STRING          COMMENT 'Employment status, mapped from BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)  COMMENT 'Parsed from BORR_ANN_INCM (comma-formatted string -> DECIMAL)',
    status              STRING          COMMENT 'Expanded from BORR_STAT_CD: ACT->Active, INA->Inactive',
    created_at          TIMESTAMP       COMMENT 'Parsed from BORR_CRET_DT (MM/DD/YYYY -> TIMESTAMP)',
    updated_at          TIMESTAMP       COMMENT 'Parsed from BORR_UPDT_DT (MM/DD/YYYY -> TIMESTAMP)',
    -- Ingestion metadata columns for audit trail
    _ingestion_ts       TIMESTAMP       COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING          COMMENT 'Source system identifier (CDW_BORR_MSTR)'
)
USING DELTA
-- Borrower table is relatively small; partition by status for efficient filtering
PARTITIONED BY (status)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Contains normalized borrower demographics and financials.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
