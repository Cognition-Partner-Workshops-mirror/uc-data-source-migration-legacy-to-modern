-- =============================================================================
-- Delta Lake Table: borrowers (Dimension)
-- =============================================================================
-- Source: CDW_BORR_MSTR (legacy all-VARCHAR borrower master table)
-- Mapped via: data/mappings/column_mappings.md
--
-- Key transformations from legacy:
--   - BORR_ID → external_id (natural key preserved for traceability)
--   - BORR_DOB_DT (MM/DD/YYYY string) → date_of_birth (DATE)
--   - BORR_ANN_INCM (comma-formatted string) → annual_income (DECIMAL)
--   - BORR_CRDT_SCR (string) → credit_score (INT)
--   - BORR_STAT_CD (ACT/INA) → status (ACTIVE/INACTIVE)
--   - BORR_REC_TYP dropped (not needed in modern schema)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    -- Surrogate key for Delta Lake (auto-generated via monotonically_increasing_id)
    borrower_id         BIGINT          COMMENT 'Surrogate primary key',

    -- Natural key from legacy CDW_BORR_MSTR.BORR_ID
    external_id         STRING NOT NULL  COMMENT 'Legacy borrower ID (e.g., B-10001)',

    -- Borrower identity fields
    first_name          STRING NOT NULL  COMMENT 'Borrower first name (from BORR_FST_NM)',
    last_name           STRING NOT NULL  COMMENT 'Borrower last name (from BORR_LST_NM)',
    middle_initial      STRING          COMMENT 'Middle initial (from BORR_MID_INIT)',
    ssn_hash            STRING          COMMENT 'Encrypted SSN (from BORR_SSN_ENCR, re-encryption recommended)',
    date_of_birth       DATE            COMMENT 'Date of birth (parsed from BORR_DOB_DT MM/DD/YYYY)',

    -- Address fields
    address_line1       STRING          COMMENT 'Primary address (from BORR_ADDR_LN1)',
    address_line2       STRING          COMMENT 'Secondary address (from BORR_ADDR_LN2)',
    city                STRING          COMMENT 'City (from BORR_CTY_NM)',
    state               STRING          COMMENT 'Two-letter state code (from BORR_ST_CD)',
    zip_code            STRING          COMMENT 'ZIP code (from BORR_ZIP_CD)',

    -- Contact fields
    phone               STRING          COMMENT 'Phone number (from BORR_PH_NBR)',
    email               STRING          COMMENT 'Email address (from BORR_EMAIL_ADDR)',

    -- Financial profile
    credit_score        INT             COMMENT 'Credit score (parsed from BORR_CRDT_SCR string)',
    employment_status   STRING          COMMENT 'Employment status (from BORR_EMP_STAT)',
    annual_income       DECIMAL(12, 2)  COMMENT 'Annual income (parsed from BORR_ANN_INCM, commas removed)',

    -- Status and audit
    status              STRING          COMMENT 'Expanded status: ACTIVE, INACTIVE (from BORR_STAT_CD ACT/INA)',
    created_at          TIMESTAMP       COMMENT 'Record creation timestamp (parsed from BORR_CRET_DT)',
    updated_at          TIMESTAMP       COMMENT 'Last update timestamp (parsed from BORR_UPDT_DT)',

    -- ETL metadata
    _ingestion_ts       TIMESTAMP       COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system      STRING          COMMENT 'Source system identifier (CDW_BORR_MSTR)'
)
USING DELTA
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Contains normalized borrower demographics, contact info, and financial profile.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
