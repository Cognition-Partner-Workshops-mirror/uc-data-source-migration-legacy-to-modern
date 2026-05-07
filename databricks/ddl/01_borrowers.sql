-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Transforms the legacy all-VARCHAR borrower master into a properly typed
-- dimension table. Drops BORR_REC_TYP (not needed in modern schema).
-- Partitioned by state for geographic query patterns common in loan servicing.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    -- Surrogate key for modern FK relationships
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    -- Legacy borrower ID preserved for traceability
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',
    first_name          STRING          NOT NULL COMMENT 'Borrower first name (was BORR_FST_NM)',
    last_name           STRING          NOT NULL COMMENT 'Borrower last name (was BORR_LST_NM)',
    middle_initial      STRING          COMMENT 'Single-char middle initial (was BORR_MID_INIT)',
    ssn_hash            STRING          COMMENT 'Encrypted SSN carried forward (was BORR_SSN_ENCR); re-encryption recommended',
    date_of_birth       DATE            COMMENT 'Parsed from MM/DD/YYYY string (was BORR_DOB_DT)',
    address_line1       STRING          COMMENT 'Primary address (was BORR_ADDR_LN1)',
    address_line2       STRING          COMMENT 'Secondary address line (was BORR_ADDR_LN2)',
    city                STRING          COMMENT 'City (was BORR_CTY_NM)',
    state               STRING          COMMENT 'Two-letter state code (was BORR_ST_CD)',
    zip_code            STRING          COMMENT 'ZIP code (was BORR_ZIP_CD)',
    phone               STRING          COMMENT 'Phone number (was BORR_PH_NBR)',
    email               STRING          COMMENT 'Email address (was BORR_EMAIL_ADDR)',
    credit_score        INT             COMMENT 'FICO score parsed from string (was BORR_CRDT_SCR); valid range 300-850',
    employment_status   STRING          COMMENT 'Employment status (was BORR_EMP_STAT)',
    annual_income       DECIMAL(12,2)   COMMENT 'Annual income parsed from comma-formatted string (was BORR_ANN_INCM)',
    status              STRING          NOT NULL COMMENT 'Expanded from BORR_STAT_CD: ACT->ACTIVE, INA->INACTIVE',
    created_at          TIMESTAMP       COMMENT 'Record creation timestamp (was BORR_CRET_DT)',
    updated_at          TIMESTAMP       COMMENT 'Last update timestamp (was BORR_UPDT_DT)',
    -- Pipeline metadata columns for lineage tracking
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp when row was ingested into Delta',
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Modern borrower dimension table migrated from CDW_BORR_MSTR. Partitioned by state for geographic query patterns.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
