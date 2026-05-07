-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy CDW)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by state for geographic query patterns common in loan servicing.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_modernized.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',
    first_name          STRING          NOT NULL    COMMENT 'Borrower first name',
    last_name           STRING          NOT NULL    COMMENT 'Borrower last name',
    middle_initial      STRING                      COMMENT 'Single-character middle initial',
    ssn_hash            STRING                      COMMENT 'Encrypted SSN carried from legacy; re-encryption recommended',
    date_of_birth       DATE                        COMMENT 'Parsed from MM/DD/YYYY string',
    address_line1       STRING                      COMMENT 'Primary street address',
    address_line2       STRING                      COMMENT 'Secondary address (apt, suite)',
    city                STRING                      COMMENT 'City name',
    state               STRING                      COMMENT 'Two-letter state code',
    zip_code            STRING                      COMMENT 'ZIP or ZIP+4 code',
    phone               STRING                      COMMENT 'Phone number with area code',
    email               STRING                      COMMENT 'Email address',
    credit_score        INT                         COMMENT 'Numeric credit score parsed from VARCHAR',
    employment_status   STRING                      COMMENT 'Employment status (EMPLOYED, SELF-EMP, RETIRED, etc.)',
    annual_income       DECIMAL(12, 2)              COMMENT 'Annual income parsed from comma-formatted string',
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
                                                    COMMENT 'Expanded from legacy codes: ACT->ACTIVE, INA->INACTIVE',
    created_at          TIMESTAMP                   COMMENT 'Record creation timestamp parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP                   COMMENT 'Last update timestamp parsed from MM/DD/YYYY',
    _legacy_record_type STRING                      COMMENT 'Original BORR_REC_TYP value preserved for audit',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Timestamp when record was migrated'
)
USING DELTA
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR'
PARTITIONED BY (state)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Constraints
ALTER TABLE loan_modernized.borrowers
    ADD CONSTRAINT borrowers_external_id_unique EXPECT (external_id IS NOT NULL)
    VIOLATION (FAIL UPDATE);

-- Optimize for common query patterns
ALTER TABLE loan_modernized.borrowers SET TBLPROPERTIES (
    'delta.dataSkippingNumIndexedCols' = '8'
);
