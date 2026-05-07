-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Core Data Warehouse)
-- =============================================================================
-- Normalized borrower dimension table with proper Spark SQL types.
-- Partitioned by status for efficient filtering on active/inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',
    first_name          STRING          NOT NULL    COMMENT 'Borrower first name',
    last_name           STRING          NOT NULL    COMMENT 'Borrower last name',
    middle_initial      STRING                      COMMENT 'Single-character middle initial',
    ssn_hash            STRING                      COMMENT 'Encrypted SSN carried from legacy; re-encryption recommended',
    date_of_birth       DATE                        COMMENT 'Parsed from MM/DD/YYYY string',
    address_line1       STRING                      COMMENT 'Primary street address',
    address_line2       STRING                      COMMENT 'Secondary address (apt, suite)',
    city                STRING,
    state               STRING                      COMMENT 'Two-letter state code',
    zip_code            STRING                      COMMENT 'ZIP or ZIP+4',
    phone               STRING,
    email               STRING,
    credit_score        INT                         COMMENT 'Parsed from VARCHAR to integer',
    employment_status   STRING                      COMMENT 'EMPLOYED, SELF-EMP, RETIRED, etc.',
    annual_income       DECIMAL(12, 2)              COMMENT 'Parsed from comma-formatted string',
    status              STRING          NOT NULL    COMMENT 'Expanded: ACT->Active, INA->Inactive',
    created_at          TIMESTAMP                   COMMENT 'Parsed from legacy BORR_CRET_DT',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from legacy BORR_UPDT_DT',
    _legacy_record_type STRING                      COMMENT 'Original BORR_REC_TYP for audit; not used in modern schema',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

-- Unique constraint on legacy external_id
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
