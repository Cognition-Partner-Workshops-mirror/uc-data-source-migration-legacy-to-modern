-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension extracted from the legacy borrower master table.
-- All VARCHAR columns converted to proper Spark SQL types.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    external_id         STRING        NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING        NOT NULL COMMENT 'Borrower first name',
    last_name           STRING        NOT NULL COMMENT 'Borrower last name',
    middle_initial      STRING        COMMENT 'Single-character middle initial',
    ssn_hash            STRING        COMMENT 'Encrypted/hashed SSN carried from legacy',
    date_of_birth       DATE          COMMENT 'Parsed from MM/DD/YYYY string',
    address_line1       STRING        COMMENT 'Primary address line',
    address_line2       STRING        COMMENT 'Secondary address line (apt, suite)',
    city                STRING,
    state               STRING        COMMENT 'Two-letter state code',
    zip_code            STRING        COMMENT 'ZIP or ZIP+4',
    phone               STRING,
    email               STRING,
    credit_score        INT           COMMENT 'Parsed from VARCHAR to integer',
    employment_status   STRING        COMMENT 'e.g. EMPLOYED, SELF-EMP, RETIRED',
    annual_income       DECIMAL(12,2) COMMENT 'Parsed from comma-formatted string',
    status              STRING        NOT NULL COMMENT 'Expanded: ACT->Active, INA->Inactive',
    created_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY string',

    CONSTRAINT borrowers_pk PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Modern borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Unique constraint on legacy external ID for FK lookups during migration
CREATE INDEX IF NOT EXISTS idx_borrowers_external_id
ON loan_warehouse.borrowers (external_id);
