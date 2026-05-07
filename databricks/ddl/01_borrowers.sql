-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table. Splits borrower data out of the
-- denormalized CDW_LN_ACCT table and serves as the single source of truth
-- for borrower attributes.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    external_id         STRING        NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING        NOT NULL COMMENT 'Borrower first name',
    last_name           STRING        NOT NULL COMMENT 'Borrower last name',
    middle_initial      STRING        COMMENT 'Single-character middle initial',
    ssn_hash            STRING        COMMENT 'Encrypted SSN carried from legacy ENC_ value',
    date_of_birth       DATE          COMMENT 'Parsed from MM/DD/YYYY string',
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING        COMMENT 'Two-letter state code',
    zip_code            STRING,
    phone               STRING,
    email               STRING,
    credit_score        INT           COMMENT 'Parsed from VARCHAR to integer',
    employment_status   STRING        COMMENT 'e.g. EMPLOYED, SELF-EMP, RETIRED',
    annual_income       DECIMAL(12,2) COMMENT 'Parsed from comma-formatted string',
    created_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY legacy BORR_CRET_DT',
    updated_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY legacy BORR_UPDT_DT',
    status              STRING        COMMENT 'Expanded: ACT->Active, INA->Inactive',
    _legacy_record_type STRING        COMMENT 'Original BORR_REC_TYP for audit (not used in modern schema)',
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT pk_borrowers PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Modern borrower dimension table migrated from CDW_BORR_MSTR'
PARTITIONED BY (state)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
