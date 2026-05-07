-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status to optimize queries filtering on active/inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_key        BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',
    first_name          STRING          NOT NULL    COMMENT 'Borrower first name (was BORR_FST_NM)',
    last_name           STRING          NOT NULL    COMMENT 'Borrower last name (was BORR_LST_NM)',
    middle_initial      STRING                      COMMENT 'Middle initial (was BORR_MID_INIT)',
    ssn_hash            STRING                      COMMENT 'Encrypted SSN (was BORR_SSN_ENCR)',
    date_of_birth       DATE                        COMMENT 'Date of birth, parsed from MM/DD/YYYY (was BORR_DOB_DT)',
    address_line1       STRING                      COMMENT 'Primary address (was BORR_ADDR_LN1)',
    address_line2       STRING                      COMMENT 'Secondary address (was BORR_ADDR_LN2)',
    city                STRING                      COMMENT 'City (was BORR_CTY_NM)',
    state               STRING                      COMMENT 'Two-letter state code (was BORR_ST_CD)',
    zip_code            STRING                      COMMENT 'ZIP code (was BORR_ZIP_CD)',
    phone               STRING                      COMMENT 'Phone number (was BORR_PH_NBR)',
    email               STRING                      COMMENT 'Email address (was BORR_EMAIL_ADDR)',
    credit_score        INT                         COMMENT 'Credit score, parsed from VARCHAR (was BORR_CRDT_SCR)',
    employment_status   STRING                      COMMENT 'Employment status (was BORR_EMP_STAT)',
    annual_income       DECIMAL(12, 2)              COMMENT 'Annual income, parsed from comma-formatted string (was BORR_ANN_INCM)',
    status              STRING          NOT NULL     COMMENT 'Expanded status: ACT->Active, INA->Inactive (was BORR_STAT_CD)',
    created_at          TIMESTAMP                   COMMENT 'Record creation timestamp, parsed from MM/DD/YYYY (was BORR_CRET_DT)',
    updated_at          TIMESTAMP                   COMMENT 'Last update timestamp, parsed from MM/DD/YYYY (was BORR_UPDT_DT)',
    _migration_source   STRING          DEFAULT 'CDW_BORR_MSTR' COMMENT 'Source table for lineage tracking',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration run'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Contains normalized borrower demographics and contact information.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.deletedFileRetentionDuration' = 'interval 30 days',
    'delta.logRetentionDuration'       = 'interval 90 days'
);

-- Unique constraint on external_id for deduplication
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
